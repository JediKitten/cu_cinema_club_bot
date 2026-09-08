"""Двойники в каталоге: тот же фильм, заведённый разными путями."""

import sqlalchemy as sa

from app.import_top import hide_duplicates
from app.models import Film
from app.models.enums import FilmStatus, InterestKind
from tests.test_weights import add_interest, make_film, make_user


async def test_untouched_twin_is_hidden(session):
    """Каталог наполнялся из двух источников: тот же фильм мог приехать дважды."""
    kept = await make_film(session, "Бойцовский клуб")
    kept.year = 1999
    kept.kp_id = 361
    twin = await make_film(session, "Бойцовский клуб")
    twin.year = 1999
    twin.tmdb_id = 550
    await session.commit()

    assert await hide_duplicates(session) == 1

    await session.refresh(kept)
    await session.refresh(twin)
    assert kept.status == FilmStatus.ACTIVE
    assert twin.status == FilmStatus.HIDDEN


async def test_the_one_people_marked_survives(session):
    """Прятать фильм, который кто-то уже отметил, нельзя: отметка указывает
    именно на эту карточку."""
    marked = await make_film(session, "Дюна")
    marked.year = 2021
    marked.tmdb_id = 438631
    fresh = await make_film(session, "Дюна")
    fresh.year = 2021
    fresh.kp_id = 4571975
    viewer = await make_user(session, "Зритель")
    await session.commit()
    await add_interest(session, viewer, marked, InterestKind.WISHLIST, 0)
    await session.commit()

    await hide_duplicates(session)

    await session.refresh(marked)
    await session.refresh(fresh)
    assert marked.status == FilmStatus.ACTIVE
    assert fresh.status == FilmStatus.HIDDEN


async def test_remakes_are_not_twins(session):
    """Год обязателен: «Дюна» 1984 и 2021 — разные фильмы."""
    old = await make_film(session, "Дюна")
    old.year = 1984
    new = await make_film(session, "Дюна")
    new.year = 2021
    await session.commit()

    assert await hide_duplicates(session) == 0
    assert await session.scalar(
        sa.select(sa.func.count()).select_from(Film).where(Film.status == FilmStatus.ACTIVE)
    ) == 2


async def test_both_marked_are_left_alone(session):
    """За обоими стоят люди — склеивать вслепую нельзя, отметки бы потерялись."""
    first = await make_film(session, "Матрица")
    first.year = 1999
    second = await make_film(session, "Матрица")
    second.year = 1999
    anya = await make_user(session, "Аня")
    borya = await make_user(session, "Боря")
    await session.commit()
    await add_interest(session, anya, first, InterestKind.WISHLIST, 0)
    await add_interest(session, borya, second, InterestKind.WISHLIST, 0)
    await session.commit()

    assert await hide_duplicates(session) == 0
