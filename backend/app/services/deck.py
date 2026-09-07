"""Лента фильмов для быстрой разметки (расширение по просьбе клуба).

Карточка на весь экран: свайп вправо — «хочу посмотреть», влево — «не моё»,
кнопка «уже смотрел». Смысл в скорости: отметить сотню фильмов списком никто
не станет, а пролистать полсотни карточек — минута.

Показываем только то, о чём человек ещё ничего не сказал: без отметки, без
просмотра и без отказа. Иначе лента возвращала бы одно и то же по кругу.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Film, FilmSkip, Interest, Watch
from app.models.enums import FilmStatus

# Сколько карточек отдаём за раз. Полтора экрана свайпов: дозагрузка успевает
# случиться незаметно, а лишнего не тянем.
PAGE = 20


def _spoken_for(user_id: int):
    """Фильмы, о которых человек уже высказался: отметил, посмотрел, пролистнул.

    Один запрос на все три случая — иначе «уже размечено» пришлось бы держать
    в двух местах и они бы разъехались.
    """
    return sa.union(
        sa.select(Interest.film_id).where(
            Interest.user_id == user_id, Interest.revoked_at.is_(None)
        ),
        sa.select(Watch.film_id).where(Watch.user_id == user_id),
        sa.select(FilmSkip.film_id).where(FilmSkip.user_id == user_id),
    )


async def next_films(
    session: AsyncSession, user_id: int, limit: int = PAGE, exclude: list[int] | None = None
) -> list[Film]:
    """Следующие карточки: сначала то, что известно большему числу людей.

    Незнакомый фильм листают не глядя, поэтому порядок — по популярности:
    у ленты один шанс на карточку, и начинать стоит с узнаваемого.
    """
    stmt = (
        sa.select(Film)
        .where(Film.status == FilmStatus.ACTIVE, Film.id.not_in(_spoken_for(user_id)))
        .order_by(sa.func.coalesce(Film.ext_votes, 0).desc(), Film.id)
        .limit(limit)
    )
    if exclude:
        # То, что уже лежит в очереди на экране: иначе дозагрузка выдала бы
        # те же карточки второй раз.
        stmt = stmt.where(Film.id.not_in(exclude))

    return list((await session.execute(stmt)).scalars())


async def skip(session: AsyncSession, user_id: int, film_id: int) -> None:
    """«Не интересно». Повтор ничего не меняет: свайпнуть дважды нельзя,
    но повторный запрос при плохой связи — обычное дело."""
    await session.execute(
        insert(FilmSkip)
        .values(user_id=user_id, film_id=film_id)
        .on_conflict_do_nothing(index_elements=[FilmSkip.user_id, FilmSkip.film_id])
    )
    await session.commit()


async def left(session: AsyncSession, user_id: int) -> int:
    """Сколько карточек ещё не размечено — лента должна говорить, что кончилась."""
    return (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Film)
            .where(Film.status == FilmStatus.ACTIVE, Film.id.not_in(_spoken_for(user_id)))
        )
        or 0
    )
