"""Оценки фильмов участниками клуба (расширение по просьбе клуба).

Пять звёзд с половинками. В базе — целые полубаллы (1..10), на экране деление
пополам: так среднее считается точно, а хранить дроби не приходится.

Оценка не привязана к показу: клуб выбирает кино в том числе по тому, что
участники видели где-то ещё. Оценка из формы после сеанса попадает сюда же —
рейтинг у фильма один, откуда бы оценка ни пришла.
"""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Film, FilmRating
from app.models.enums import FilmStatus

# Шкала на экране: пять звёзд с половинками.
MAX_STARS = 5
MAX_SCORE = MAX_STARS * 2


class RatingError(ValueError):
    """Причину показываем как есть."""


class FilmNotFound(RatingError):
    """Отдельно от ошибок шкалы: это не «вы неправильно нажали», а «нечего оценивать»."""


@dataclass(frozen=True, slots=True)
class Summary:
    """Средняя оценка клуба в звёздах и число оценивших."""

    average: float | None
    votes: int


def to_stars(score: int | None) -> float | None:
    return None if score is None else score / 2


def to_score(stars: float) -> int:
    """Звёзды с половинками — в полубаллы. Всё остальное отвергаем."""
    score = round(stars * 2)
    if abs(stars * 2 - score) > 1e-6:
        raise RatingError("Оценка ставится с шагом в ползвезды")
    if not 1 <= score <= MAX_SCORE:
        raise RatingError(f"Оценка — от 0,5 до {MAX_STARS}")
    return score


async def set_rating(
    session: AsyncSession, user_id: int, film_id: int, stars: float | None, source: str = "catalog"
) -> Summary:
    """Ставит или снимает оценку. Возвращает новый рейтинг фильма."""
    film = await session.get(Film, film_id)
    if film is None or film.status == FilmStatus.HIDDEN:
        raise FilmNotFound("Фильм не найден")

    if stars is None:
        await session.execute(
            sa.delete(FilmRating).where(
                FilmRating.user_id == user_id, FilmRating.film_id == film_id
            )
        )
    else:
        score = to_score(stars)
        stmt = insert(FilmRating).values(
            user_id=user_id, film_id=film_id, score=score, source=source
        )
        # Оценку меняют: повторная — не вторая запись, а замена прежней.
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[FilmRating.user_id, FilmRating.film_id],
                set_={"score": score, "source": source, "updated_at": sa.func.now()},
            )
        )
    await session.commit()
    return (await summaries(session, [film_id])).get(film_id, Summary(None, 0))


async def my_rating(session: AsyncSession, user_id: int, film_id: int) -> float | None:
    score = await session.scalar(
        sa.select(FilmRating.score).where(
            FilmRating.user_id == user_id, FilmRating.film_id == film_id
        )
    )
    return to_stars(score)


async def summaries(session: AsyncSession, film_ids: list[int]) -> dict[int, Summary]:
    """Средние оценки пачкой: списку фильмов нужен один запрос, а не по одному."""
    if not film_ids:
        return {}
    rows = await session.execute(
        sa.select(
            FilmRating.film_id,
            sa.func.avg(FilmRating.score),
            sa.func.count(FilmRating.score),
        )
        .where(FilmRating.film_id.in_(film_ids))
        .group_by(FilmRating.film_id)
    )
    return {
        film_id: Summary(average=round(float(average) / 2, 2), votes=votes)
        for film_id, average, votes in rows
    }


async def summary(session: AsyncSession, film_id: int) -> Summary:
    return (await summaries(session, [film_id])).get(film_id, Summary(None, 0))
