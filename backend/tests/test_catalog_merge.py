"""Склейка двойников каталога.

Каталог наполняется из двух источников, и один фильм попадает в него дважды.
Импорт прячет только тех двойников, за которыми никто не стоит; пару, где обе
карточки кому-то дороги, он оставляет человеку — и вот чем человек её склеит.
"""

import sqlalchemy as sa

from app.models import Favourite, Film, FilmRating, Interest, Watch
from app.models.enums import FilmStatus, InterestKind
from app.services import catalog, interests, ratings
from tests.test_weights import make_film, make_user


async def twins(session) -> tuple[Film, Film]:
    """Один фильм, заведённый дважды: из Кинопоиска и из TMDB."""
    from_kp = await make_film(session, "Железный человек")
    from_kp.title_orig = "Iron Man"
    from_kp.year = 2008
    from_kp.kp_id = 61237

    from_tmdb = await make_film(session, "Железный человек")
    from_tmdb.title_orig = "Iron Man"
    from_tmdb.year = 2008
    from_tmdb.tmdb_id = 1726
    await session.commit()
    return from_kp, from_tmdb


async def test_duplicates_are_found_with_the_same_keys_as_the_import(session):
    keep, drop = await twins(session)
    await make_film(session, "Совсем другое кино")
    await session.commit()

    pairs = await catalog.duplicates(session)

    assert len(pairs) == 1
    assert {pairs[0].keep.id, pairs[0].drop.id} == {keep.id, drop.id}
    # При равенстве следов остаётся карточка Кинопоиска: у неё живой постер.
    assert pairs[0].keep.id == keep.id


async def test_merge_moves_everything_people_said(session):
    """Отметки, просмотры и оценки переезжают на оставшуюся карточку."""
    keep, drop = await twins(session)
    user = await make_user(session, "Зритель")
    await session.commit()

    await interests.set_mark(session, user.id, drop.id, InterestKind.WISHLIST, 14, 10)
    await interests.set_watched(session, user.id, drop.id, True, 14)
    await ratings.set_rating(session, user.id, drop.id, 4)
    session.add(Favourite(user_id=user.id, film_id=drop.id, position=0))
    await session.commit()

    moved = await catalog.merge(session, keep.id, drop.id)

    assert moved  # что-то перенесли
    for model in (Interest, Watch, FilmRating, Favourite):
        left = await session.scalar(
            sa.select(sa.func.count()).select_from(model).where(model.film_id == drop.id)
        )
        landed = await session.scalar(
            sa.select(sa.func.count()).select_from(model).where(model.film_id == keep.id)
        )
        assert left == 0, model.__tablename__
        assert landed == 1, model.__tablename__


async def test_merge_hides_the_double_and_keeps_both_ids(session):
    """Карточка не удаляется, а прячется, и забирает себе id обоих источников.

    Удалить нельзя: ссылка на неё могла разойтись. А оба id нужны, чтобы
    следующий импорт не завёл двойника заново.
    """
    keep, drop = await twins(session)

    await catalog.merge(session, keep.id, drop.id)
    await session.refresh(keep)
    await session.refresh(drop)

    assert drop.status == FilmStatus.HIDDEN
    assert keep.status == FilmStatus.ACTIVE
    assert (keep.kp_id, keep.tmdb_id) == (61237, 1726)
    assert drop.tmdb_id is None


async def test_merge_does_not_choke_on_what_the_person_said_twice(session):
    """Один человек отметил обе карточки — уникальный ключ не должен всё уронить."""
    keep, drop = await twins(session)
    user = await make_user(session, "Зритель")
    await session.commit()

    for film in (keep, drop):
        await interests.set_mark(session, user.id, film.id, InterestKind.WISHLIST, 14, 10)
        await ratings.set_rating(session, user.id, film.id, 4)

    await catalog.merge(session, keep.id, drop.id)

    # Осталось ровно по одной записи — та, что и так была на оставшейся.
    for model in (Interest, FilmRating):
        total = await session.scalar(
            sa.select(sa.func.count()).select_from(model).where(model.user_id == user.id)
        )
        assert total == 1, model.__tablename__


async def test_merged_pair_disappears_from_the_list(session):
    keep, drop = await twins(session)
    await catalog.merge(session, keep.id, drop.id)

    assert await catalog.duplicates(session) == []


async def test_merge_refuses_nonsense(session):
    import pytest

    keep, _ = await twins(session)
    with pytest.raises(catalog.CatalogError, match="одна и та же"):
        await catalog.merge(session, keep.id, keep.id)
    with pytest.raises(catalog.CatalogError, match="не найдена"):
        await catalog.merge(session, keep.id, 999_999)
