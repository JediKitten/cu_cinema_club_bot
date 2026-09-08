"""Лента для быстрой разметки (расширение по просьбе клуба)."""

import sqlalchemy as sa

from app.models import Film, FilmSkip
from app.models.enums import FilmStatus, InterestKind
from app.services import deck, ratings, social
from app.services import interests as marks
from tests.conftest import SUPERADMIN_TG_ID, login
from tests.test_weights import add_interest, make_film, make_user


async def catalog(session, count: int = 5) -> list[Film]:
    """Одинаково безвестные фильмы: ни один сигнал не тянет их вперёд,
    поэтому в таком каталоге проверяется только состав ленты, не порядок."""
    films = []
    for index in range(count):
        films.append(await make_film(session, f"Фильм {index}"))
    await session.commit()
    return films


def ids(picks: list[deck.Suggestion]) -> list[int]:
    return [pick.film.id for pick in picks]


async def test_deck_shows_everything_unmarked(session):
    films = await catalog(session)
    viewer = await make_user(session, "Зритель")
    await session.commit()

    picks = await deck.next_films(session, viewer.id)

    assert sorted(ids(picks)) == sorted(film.id for film in films)


async def test_film_a_friend_rated_high_comes_first(session):
    """Ради этого лента и стала рекомендацией: оценка друга весит больше всего."""
    films = await catalog(session, 4)
    viewer = await make_user(session, "Зритель")
    friend = await make_user(session, "Друг")
    stranger = await make_user(session, "Незнакомец")
    await session.commit()

    await social.follow(session, viewer.id, friend.id)
    # Оценка постороннего человека — сигнал клуба, а не друга, и весит меньше.
    await ratings.set_rating(session, stranger.id, films[2].id, 5)
    await ratings.set_rating(session, friend.id, films[3].id, 5)

    picks = await deck.next_films(session, viewer.id)

    assert ids(picks)[0] == films[3].id
    assert picks[0].reason == "Друг оценил на 5,0"


async def test_friends_low_rating_does_not_recommend(session):
    """«Так себе» — не рекомендация: ниже трёх звёзд сигнал равен нулю."""
    films = await catalog(session, 2)
    viewer = await make_user(session, "Зритель")
    friend = await make_user(session, "Друг")
    await session.commit()

    await social.follow(session, viewer.id, friend.id)
    await ratings.set_rating(session, friend.id, films[0].id, 1.5)

    picks = await deck.next_films(session, viewer.id)

    assert {pick.reason for pick in picks} == {None}


async def test_friends_wishlist_lifts_a_film(session):
    films = await catalog(session, 3)
    viewer = await make_user(session, "Зритель")
    friend = await make_user(session, "Друг")
    await session.commit()

    await social.follow(session, viewer.id, friend.id)
    await add_interest(session, friend, films[1], InterestKind.WISHLIST, 0)
    await session.commit()

    picks = await deck.next_films(session, viewer.id)

    assert ids(picks)[0] == films[1].id
    assert picks[0].reason == "Друг хочет посмотреть"


async def test_taste_is_built_from_marks_and_ratings(session):
    """Профиль вкуса собирается из того, что уже есть, — ничего нового не пишем."""
    viewer = await make_user(session, "Зритель")
    loved = await make_film(session, "Любимое")
    loved.genres = ["драма", "детектив"]
    marked = await make_film(session, "Отмеченное")
    marked.genres = ["драма"]
    await session.commit()

    await ratings.set_rating(session, viewer.id, loved.id, 5)
    await add_interest(session, viewer, marked, InterestKind.WISHLIST, 0)
    await session.commit()

    profile = await deck.taste(session, viewer.id)

    assert profile.genres["драма"] == 1.0
    assert profile.genres["детектив"] < 1.0


async def test_films_like_what_you_love_come_earlier(session):
    viewer = await make_user(session, "Зритель")
    loved = await make_film(session, "Любимое")
    loved.genres = ["вестерн"]
    similar = await make_film(session, "Похожее")
    similar.genres = ["вестерн"]
    other = await make_film(session, "Другое")
    other.genres = ["мюзикл"]
    await session.commit()
    await ratings.set_rating(session, viewer.id, loved.id, 5)

    picks = await deck.next_films(session, viewer.id)

    # Оценённый фильм из ленты уходит: человек о нём уже высказался.
    assert ids(picks) == [similar.id, other.id]
    assert picks[0].reason == "Похоже на ваш вкус: вестерн"


async def test_known_films_beat_unknown_ones_when_nothing_else_is_known(session):
    """Новичку без друзей и отметок лента показывает узнаваемое: незнакомую
    карточку листают не глядя."""
    films = await catalog(session, 2)
    films[1].ext_rating = 8.5
    films[1].ext_votes = 500_000
    await session.commit()
    viewer = await make_user(session, "Зритель")
    await session.commit()

    picks = await deck.next_films(session, viewer.id)

    assert ids(picks)[0] == films[1].id


async def test_order_is_the_same_between_pages(session):
    """Случайность у каждого своя, но постоянная: иначе дозагрузка
    перетасовывала бы очередь и карточки терялись бы, не показавшись."""
    await catalog(session, 12)
    viewer = await make_user(session, "Зритель")
    await session.commit()

    first = ids(await deck.next_films(session, viewer.id))
    again = ids(await deck.next_films(session, viewer.id))

    assert first == again


async def test_the_shuffle_differs_between_people(session):
    await catalog(session, 12)
    anya = await make_user(session, "Аня")
    borya = await make_user(session, "Боря")
    await session.commit()

    assert ids(await deck.next_films(session, anya.id)) != ids(
        await deck.next_films(session, borya.id)
    )


async def test_marked_rated_watched_and_skipped_films_do_not_come_back(session):
    films = await catalog(session)
    viewer = await make_user(session, "Зритель")
    await session.commit()

    await add_interest(session, viewer, films[0], InterestKind.WISHLIST, 0)
    await marks.set_watched(session, viewer.id, films[1].id, True, soon_ttl_days=14)
    await deck.skip(session, viewer.id, films[2].id)
    await ratings.set_rating(session, viewer.id, films[3].id, 4)

    picks = await deck.next_films(session, viewer.id)

    assert ids(picks) == [films[4].id]


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
    await catalog(session)
    viewer = await make_user(session, "Зритель")
    await session.commit()

    held = ids(await deck.next_films(session, viewer.id, limit=2))
    more = ids(await deck.next_films(session, viewer.id, limit=2, exclude=held))

    assert not set(held) & set(more)


async def test_hidden_films_never_appear(session):
    films = await catalog(session, 2)
    films[0].status = FilmStatus.HIDDEN
    viewer = await make_user(session, "Зритель")
    await session.commit()

    picks = await deck.next_films(session, viewer.id)

    assert ids(picks) == [films[1].id]


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
    assert len(first["cards"]) == 2
    assert first["left"] == 3
    # На карточке есть всё, чтобы решить за секунду.
    assert "overview" in first["cards"][0]
    assert "reason" in first["cards"][0]

    shown = [card["id"] for card in first["cards"]]

    # Свайп влево.
    skipped = await client.post(f"/api/films/{shown[0]}/skip", headers=headers)
    assert skipped.status_code == 204

    # Свайп вправо — обычная отметка «Желаемое».
    liked = await client.post(
        f"/api/films/{shown[1]}/interest", json={"kind": "wishlist"}, headers=headers
    )
    assert liked.status_code == 201

    after = (await client.get("/api/films/deck", headers=headers)).json()
    assert [card["id"] for card in after["cards"]] == [
        film.id for film in films if film.id not in shown
    ]
    assert after["left"] == 1


async def test_skipping_an_unknown_film_is_a_404(client):
    me = await login(client, SUPERADMIN_TG_ID, "Главный")

    missing = await client.post(
        "/api/films/999999/skip", headers={"Authorization": f"Bearer {me['token']}"}
    )
    assert missing.status_code == 404
