"""Этап 2 — фильмы и время (§6).

Пользователь делает два независимых действия: отмечает все фильмы шорт-листа,
на которые пошёл бы, и все вечера, когда свободен. Это множественный выбор,
а не ранжирование: сравнивать фильмы между собой мы не просим.
"""

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Availability, Film, FilmVote, Round, ShortlistItem, Slot
from app.models.enums import RoundStage


class VotingError(ValueError):
    """Голосование сейчас невозможно — показываем причину пользователю."""


def ensure_open(round_: Round | None) -> Round:
    if round_ is None:
        raise VotingError("Сейчас голосования нет")
    if round_.stage != RoundStage.SLOT_VOTING:
        raise VotingError("Голосование закрыто")
    return round_


async def shortlist_films(session: AsyncSession, round_: Round) -> list[Film]:
    rows = (
        await session.execute(
            sa.select(Film)
            .join(ShortlistItem, ShortlistItem.film_id == Film.id)
            .where(ShortlistItem.round_id == round_.id)
            .order_by(ShortlistItem.position)
        )
    ).scalars()
    return list(rows)


async def open_slots(session: AsyncSession, round_: Round) -> list[Slot]:
    """Заблокированные вечера не показываем: назначить на них показ нельзя,
    и отмечаться в них бессмысленно."""
    rows = (
        await session.execute(
            sa.select(Slot)
            .where(Slot.round_id == round_.id, Slot.blocked.is_(False))
            .order_by(Slot.starts_at)
        )
    ).scalars()
    return list(rows)


async def my_votes(session: AsyncSession, round_: Round, user_id: int) -> list[int]:
    rows = await session.execute(
        sa.select(FilmVote.film_id).where(
            FilmVote.round_id == round_.id, FilmVote.user_id == user_id
        )
    )
    return sorted(rows.scalars())


async def my_availability(session: AsyncSession, round_: Round, user_id: int) -> list[int]:
    rows = await session.execute(
        sa.select(Availability.slot_id).where(
            Availability.round_id == round_.id, Availability.user_id == user_id
        )
    )
    return sorted(rows.scalars())


async def toggle_vote(
    session: AsyncSession, round_: Round, user_id: int, film_id: int
) -> tuple[bool, list[int]]:
    """Переключает один голос. Возвращает («теперь отмечен», весь выбор).

    Отдельно от `set_votes` намеренно. Кнопка в чате присылает одно нажатие,
    и переписывать ради него весь набор значило бы потерять соседний голос,
    если два нажатия пришли одновременно: тапают по кнопкам быстро и подряд.
    """
    ensure_open(round_)

    allowed = {film.id for film in await shortlist_films(session, round_)}
    if film_id not in allowed:
        raise VotingError("Этого фильма нет в шорт-листе")

    removed = await session.execute(
        sa.delete(FilmVote).where(
            FilmVote.round_id == round_.id,
            FilmVote.user_id == user_id,
            FilmVote.film_id == film_id,
        )
    )
    now_on = removed.rowcount == 0
    if now_on:
        await session.execute(
            insert(FilmVote)
            .values(round_id=round_.id, user_id=user_id, film_id=film_id)
            .on_conflict_do_nothing(
                index_elements=[FilmVote.round_id, FilmVote.user_id, FilmVote.film_id]
            )
        )
    await session.commit()
    return now_on, await my_votes(session, round_, user_id)


async def set_votes(
    session: AsyncSession, round_: Round, user_id: int, film_ids: list[int]
) -> list[int]:
    """Заменяет выбор фильмов целиком: голосование — это состояние, а не история."""
    ensure_open(round_)

    allowed = {film.id for film in await shortlist_films(session, round_)}
    unknown = [film_id for film_id in film_ids if film_id not in allowed]
    if unknown:
        raise VotingError("Можно выбирать только фильмы из шорт-листа")

    await session.execute(
        sa.delete(FilmVote).where(FilmVote.round_id == round_.id, FilmVote.user_id == user_id)
    )
    session.add_all(
        FilmVote(round_id=round_.id, user_id=user_id, film_id=film_id)
        for film_id in dict.fromkeys(film_ids)
    )
    await session.commit()
    return sorted(set(film_ids))


async def set_availability(
    session: AsyncSession, round_: Round, user_id: int, slot_ids: list[int]
) -> list[int]:
    ensure_open(round_)

    allowed = {slot.id for slot in await open_slots(session, round_)}
    unknown = [slot_id for slot_id in slot_ids if slot_id not in allowed]
    if unknown:
        raise VotingError("Этот вечер недоступен")

    await session.execute(
        sa.delete(Availability).where(
            Availability.round_id == round_.id, Availability.user_id == user_id
        )
    )
    session.add_all(
        Availability(round_id=round_.id, user_id=user_id, slot_id=slot_id)
        for slot_id in dict.fromkeys(slot_ids)
    )
    await session.commit()
    return sorted(set(slot_ids))


@dataclass(slots=True)
class Matrix:
    """Матрица «фильм × слот» для администратора (§6).

    В ячейке — сколько людей одновременно выбрали этот фильм и свободны в этот
    вечер. Это и есть ожидаемая явка, если назначить показ сюда.
    """

    film_ids: list[int]
    slot_ids: list[int]
    cells: dict[tuple[int, int], int] = field(default_factory=dict)
    film_votes: dict[int, int] = field(default_factory=dict)
    slot_free: dict[int, int] = field(default_factory=dict)
    # Проголосовали за фильмы, но не отметили ни одного вечера — их голоса
    # ни на что не влияют, и админу полезно знать масштаб (§6).
    voters_without_evening: int = 0

    def cell(self, film_id: int, slot_id: int) -> int:
        return self.cells.get((film_id, slot_id), 0)


async def build_matrix(session: AsyncSession, round_: Round) -> Matrix:
    films = await shortlist_films(session, round_)
    slots = await open_slots(session, round_)
    matrix = Matrix(film_ids=[f.id for f in films], slot_ids=[s.id for s in slots])

    # Пересечение считаем одним запросом: пользователь попадает в ячейку, если
    # он и голосовал за фильм, и свободен в этот вечер.
    cells = await session.execute(
        sa.select(
            FilmVote.film_id,
            Availability.slot_id,
            sa.func.count(sa.distinct(FilmVote.user_id)),
        )
        .join(
            Availability,
            sa.and_(
                Availability.user_id == FilmVote.user_id,
                Availability.round_id == FilmVote.round_id,
            ),
        )
        .where(FilmVote.round_id == round_.id)
        .group_by(FilmVote.film_id, Availability.slot_id)
    )
    open_slot_ids = set(matrix.slot_ids)
    for film_id, slot_id, count in cells:
        if slot_id in open_slot_ids:
            matrix.cells[(film_id, slot_id)] = count

    votes = await session.execute(
        sa.select(FilmVote.film_id, sa.func.count())
        .where(FilmVote.round_id == round_.id)
        .group_by(FilmVote.film_id)
    )
    matrix.film_votes = {film_id: count for film_id, count in votes}

    free = await session.execute(
        sa.select(Availability.slot_id, sa.func.count())
        .where(Availability.round_id == round_.id)
        .group_by(Availability.slot_id)
    )
    matrix.slot_free = {slot_id: count for slot_id, count in free if slot_id in open_slot_ids}

    voters = sa.select(sa.distinct(FilmVote.user_id)).where(FilmVote.round_id == round_.id)
    with_evening = sa.select(sa.distinct(Availability.user_id)).where(
        Availability.round_id == round_.id
    )
    matrix.voters_without_evening = (
        await session.scalar(
            sa.select(sa.func.count()).select_from(
                voters.except_(with_evening).subquery()
            )
        )
        or 0
    )
    return matrix
