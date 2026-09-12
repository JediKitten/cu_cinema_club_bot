"""Склейка двойников каталога (расширение по просьбе клуба).

Каталог наполняется из двух источников, и один фильм попадает в него дважды:
из Кинопоиска и из TMDB. Импорт таких двойников прячет сам
(`import_top.hide_duplicates`), но только пока за карточкой никто не стоит:
склеивать вслепую нельзя — чужие отметки и оценки при этом потерялись бы.
Пары, за которыми есть следы людей, он оставляет «на ручное решение», а
инструмента для этого решения до сих пор не было.

Здесь он и есть. Склейка переносит на оставшуюся карточку всё, что люди
успели про неё сказать, и прячет вторую — не удаляет: ссылки на неё могли
разойтись, а скрытая карточка честно ведёт себя как отсутствующая.
"""

import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Favourite,
    Feedback,
    Film,
    FilmRating,
    FilmRequest,
    FilmSkip,
    FilmVote,
    Interest,
    Referral,
    Screening,
    ShortlistItem,
    TournamentOption,
    Watch,
)
from app.models.enums import FilmStatus
from app.services import matching

logger = logging.getLogger(__name__)


class CatalogError(ValueError):
    """Причину показываем администратору как есть."""


# Что переносим и по какому ключу строки считаются одной и той же.
# Ключ — то, что делает вторую строку лишней: один человек не может дважды
# отметить один фильм, один цикл не может дважды взять его в шорт-лист.
MOVED: tuple[tuple[type, tuple[str, ...]], ...] = (
    (Interest, ("user_id",)),
    (Watch, ("user_id",)),
    (FilmRating, ("user_id",)),
    (Favourite, ("user_id",)),
    (FilmSkip, ("user_id",)),
    (Referral, ("invitee_id",)),
    (ShortlistItem, ("round_id",)),
    (FilmVote, ("round_id", "user_id")),
    (Screening, ("round_id",)),
    # У отзыва ключ — показ: на одном сеансе человек оставляет один отзыв,
    # а фильм там просто ссылка.
    (Feedback, ("screening_id", "user_id")),
    # У варианта турнира и заявки ограничений нет: переносим всё.
    (TournamentOption, ()),
)


@dataclass(slots=True)
class Duplicate:
    """Пара карточек, которые выглядят одним фильмом."""

    keep: Film
    drop: Film
    keep_traces: int
    drop_traces: int


async def _traces(session: AsyncSession) -> dict[int, int]:
    """Сколько следов людей за каждой карточкой: отметки, просмотры, оценки."""
    counts: dict[int, int] = {}
    for model in (Interest, Watch, FilmRating, Favourite):
        rows = await session.execute(
            sa.select(model.film_id, sa.func.count()).group_by(model.film_id)
        )
        for film_id, count in rows:
            counts[film_id] = counts.get(film_id, 0) + count
    return counts


async def duplicates(session: AsyncSession) -> list[Duplicate]:
    """Двойники среди живых карточек — те же ключи, что у импорта."""
    films = list(
        (
            await session.execute(
                sa.select(Film).where(Film.status == FilmStatus.ACTIVE).order_by(Film.id)
            )
        )
        .scalars()
        .all()
    )
    traces = await _traces(session)

    found: list[Duplicate] = []
    seen: dict[tuple[str, int], Film] = {}
    for film in films:
        keys = matching.keys(film.title_ru, film.title_orig, film.year)
        twin = next((seen[key] for key in keys if key in seen), None)
        if twin is not None:
            # Оставляем ту, за которой больше следов; при равенстве — карточку
            # Кинопоиска: у неё русское описание и живой у нас постер.
            keep, drop = sorted(
                (twin, film),
                key=lambda f: (traces.get(f.id, 0), f.kp_id is not None),
                reverse=True,
            )
            found.append(
                Duplicate(
                    keep=keep,
                    drop=drop,
                    keep_traces=traces.get(keep.id, 0),
                    drop_traces=traces.get(drop.id, 0),
                )
            )
            keys |= matching.keys(twin.title_ru, twin.title_orig, twin.year)
            film = keep
        for key in keys:
            seen[key] = film
    return found


async def merge(
    session: AsyncSession, keep_id: int, drop_id: int, actor_id: int | None = None
) -> dict[str, int]:
    """Сливает карточку `drop` в `keep`. Возвращает, сколько чего перенесено.

    Строка, у которой на оставшейся карточке уже есть пара (тот же человек,
    тот же цикл), не переносится, а удаляется: иначе она упрётся в уникальный
    ключ, и вся склейка развалится на полпути. Терять при этом нечего —
    человек уже сказал то же самое про ту же карточку.
    """
    if keep_id == drop_id:
        raise CatalogError("Это одна и та же карточка")

    keep = await session.get(Film, keep_id)
    drop = await session.get(Film, drop_id)
    if keep is None or drop is None:
        raise CatalogError("Карточка не найдена")

    moved: dict[str, int] = {}
    for model, key in MOVED:
        table = model.__tablename__
        if key:
            columns = ", ".join(key)
            # Сначала убираем то, что столкнётся с уже существующим.
            dropped = await session.execute(
                sa.text(
                    f"DELETE FROM {table} WHERE film_id = :drop AND ({columns}) IN "
                    f"(SELECT {columns} FROM {table} WHERE film_id = :keep)"
                ),
                {"drop": drop_id, "keep": keep_id},
            )
            if dropped.rowcount:
                moved[f"{table} (дубли)"] = dropped.rowcount
        result = await session.execute(
            sa.update(model)
            .where(model.film_id == drop_id)
            .values(film_id=keep_id)
        )
        if result.rowcount:
            moved[table] = result.rowcount

    # Заявки ведут на карточку по отдельному полю.
    requests = await session.execute(
        sa.update(FilmRequest)
        .where(FilmRequest.resolved_film_id == drop_id)
        .values(resolved_film_id=keep_id)
    )
    if requests.rowcount:
        moved["film_requests"] = requests.rowcount

    # Идентификаторы источников забираем себе: после склейки карточка знает
    # оба, и следующий импорт не заведёт двойника заново. Сначала отпускаем их
    # у второй карточки и только потом присваиваем — id уникальны, и порядок
    # «присвоить, потом отпустить» упирается в индекс на полпути.
    borrowed: dict[str, int] = {}
    for field in ("tmdb_id", "kp_id"):
        mine, theirs = getattr(keep, field), getattr(drop, field)
        if mine is None and theirs is not None:
            borrowed[field] = theirs
            setattr(drop, field, None)
    await session.flush()
    for field, value in borrowed.items():
        setattr(keep, field, value)
    for field in ("tmdb_rating", "tmdb_votes", "kp_rating", "kp_votes", "kp_top250"):
        if getattr(keep, field, None) is None and getattr(drop, field, None) is not None:
            setattr(keep, field, getattr(drop, field))

    # Не удаляем: ссылка на карточку могла разойтись, а скрытая ведёт себя
    # как отсутствующая — и остаётся следом того, что склейка была.
    drop.status = FilmStatus.HIDDEN
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="film",
            entity_id=keep_id,
            action="merge",
            payload={"dropped": drop_id, "moved": moved},
        )
    )
    await session.commit()
    logger.info("Склеено: %s (%s) ← %s", keep.title_ru, keep_id, drop_id)
    return moved
