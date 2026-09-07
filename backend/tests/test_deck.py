"""Лента для быстрой разметки (расширение по просьбе клуба)."""

import sqlalchemy as sa

from app.models import Film, FilmSkip
from app.models.enums import FilmStatus, InterestKind
from app.services import deck
from app.services import interests as marks
from tests.conftest import SUPERADMIN_TG_ID, login
from tests.test_weights import add_interest, make_film, make_user


async def catalog(session, count: int = 5) -> list[Film]:
    """Фильмы с разной популярностью: лента показывает узнаваемое первым."""
    films = []
    for index in range(count):
        film = await make_film(session, f"Фильм {index}")
        film.ext_votes = 1000 - index
        films.append(film)
    await session.commit()
    return films


async def test_deck_shows_the_most_popular_first(session):
    films = await catalog(session)
    viewer = await make_user(session, "Зритель")
    await session.commit()

    cards = await deck.next_films(session, viewer.id, limit=3)

    assert [film.id for film in cards] == [films[0].id, films[1].id, films[2].id]


async def test_marked_watched_and_skipped_films_do_not_come_back(session):
    films = await catalog(session)
    viewer = await make_user(session, "Зритель")
    await session.commit()

    await add_interest(session, viewer, films[0], InterestKind.WISHLIST, 0)
    await marks.set_watched(session, viewer.id, films[1].id, True, soon_ttl_days=14)
    await deck.skip(session, viewer.id, films[2].id)

    cards = await deck.next_films(session, viewer.id)

    assert [film.id for film in cards] == [films[3].id, films[4].id]


async def test_skip_twice_is_harmless(session):
    films = await catalog(session, 1)
    viewer = await make_user(session, "Зритель")
    await session.commit()

    await deck.skip(session, viewer.id, films[0].id)
    await deck.skip(session, viewer.id, films[0].id)

    total = await session.scalar(sa.select(sa.func.count()).select_from(FilmSkip))
    assert total == 1


async def test_deck_skips_what_is_already_on_screen(session):
    """Дозагрузка не должна выдавать карточки, которые ещё лежат в очереди."""
    films = await catalog(session)
    viewer = await make_user(session, "Зритель")
    await session.commit()

    cards = await deck.next_films(session, viewer.id, limit=2, exclude=[films[0].id, films[1].id])

    assert [film.id for film in cards] == [films[2].id, films[3].id]


async def test_hidden_films_never_appear(session):
    films = await catalog(session, 2)
    films[0].status = FilmStatus.HIDDEN
    viewer = await make_user(session, "Зритель")
    await session.commit()

    cards = await deck.next_films(session, viewer.id)

    assert [film.id for film in cards] == [films[1].id]


async def test_left_counts_what_is_still_unmarked(session):
    films = await catalog(session, 4)
    viewer = await make_user(session, "Зритель")
    await session.commit()
    await deck.skip(session, viewer.id, films[0].id)

    assert await deck.left(session, viewer.id) == 3


async def test_deck_over_http_and_swipes(client, session):
    films = await catalog(session, 3)
    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    headers = {"Authorization": f"Bearer {me['token']}"}

    first = (await client.get("/api/films/deck?limit=2", headers=headers)).json()
    assert [card["id"] for card in first["cards"]] == [films[0].id, films[1].id]
    assert first["left"] == 3
    # На карточке есть всё, чтобы решить за секунду.
    assert "overview" in first["cards"][0]

    # Свайп влево.
    skipped = await client.post(f"/api/films/{films[0].id}/skip", headers=headers)
    assert skipped.status_code == 204

    # Свайп вправо — обычная отметка «Желаемое».
    liked = await client.post(
        f"/api/films/{films[1].id}/interest", json={"kind": "wishlist"}, headers=headers
    )
    assert liked.status_code == 201

    after = (await client.get("/api/films/deck", headers=headers)).json()
    assert [card["id"] for card in after["cards"]] == [films[2].id]
    assert after["left"] == 1


async def test_skipping_an_unknown_film_is_a_404(client):
    me = await login(client, SUPERADMIN_TG_ID, "Главный")

    missing = await client.post(
        "/api/films/999999/skip", headers={"Authorization": f"Bearer {me['token']}"}
    )
    assert missing.status_code == 404
