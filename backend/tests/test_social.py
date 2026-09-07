"""Профили, друзья и лента (расширение по просьбе клуба)."""

import pytest
import sqlalchemy as sa

from app.models import Friendship, User
from app.models.enums import InterestKind
from app.services import attendance as att
from app.services import social
from app.services.social import SocialError
from tests.conftest import SUPERADMIN_TG_ID, login
from tests.test_analytics import held_screening
from tests.test_weights import add_interest, make_film, make_user


async def two_people(session) -> tuple[User, User]:
    first = await make_user(session, "Аня")
    second = await make_user(session, "Боря")
    await session.commit()
    return first, second


async def test_adding_one_way_is_a_subscription(session):
    """«Добавить» работает сразу: подтверждения ждать не нужно."""
    anya, borya = await two_people(session)

    relation = await social.follow(session, anya.id, borya.id)

    assert relation.following is True
    assert relation.follower is False
    assert relation.friends is False


async def test_friendship_appears_when_both_added_each_other(session):
    anya, borya = await two_people(session)

    await social.follow(session, anya.id, borya.id)
    back = await social.follow(session, borya.id, anya.id)

    assert back.friends is True
    assert (await social.relation(session, anya.id, borya.id)).friends is True

    circle = await social.circle(session, anya.id)
    assert [u.display_name for u in circle["friends"]] == ["Боря"]
    assert circle["following"] == []
    assert circle["followers"] == []


async def test_circle_separates_one_way_links(session):
    """Односторонняя связь — не дружба, и выдавать её за дружбу нельзя."""
    anya, borya = await two_people(session)
    vera = await make_user(session, "Вера")
    await session.commit()

    await social.follow(session, anya.id, borya.id)
    await social.follow(session, vera.id, anya.id)

    circle = await social.circle(session, anya.id)
    assert [u.display_name for u in circle["following"]] == ["Боря"]
    assert [u.display_name for u in circle["followers"]] == ["Вера"]
    assert circle["friends"] == []


async def test_adding_twice_changes_nothing(session):
    anya, borya = await two_people(session)

    await social.follow(session, anya.id, borya.id)
    await social.follow(session, anya.id, borya.id)

    total = await session.scalar(sa.select(sa.func.count()).select_from(Friendship))
    assert total == 1


async def test_you_cannot_befriend_yourself(session):
    anya, _ = await two_people(session)

    with pytest.raises(SocialError, match="Себя"):
        await social.follow(session, anya.id, anya.id)


async def test_unfollow_leaves_the_other_direction_alone(session):
    anya, borya = await two_people(session)
    await social.follow(session, anya.id, borya.id)
    await social.follow(session, borya.id, anya.id)

    await social.unfollow(session, anya.id, borya.id)

    relation = await social.relation(session, anya.id, borya.id)
    assert relation.following is False
    # Боря по-прежнему следит за Аней: отписка — не разрыв с обеих сторон.
    assert relation.follower is True


async def test_favourites_are_ordered_and_limited(session):
    anya, _ = await two_people(session)
    films = [await make_film(session, f"Фильм {i}") for i in range(5)]
    await session.commit()

    chosen = [films[3].id, films[0].id, films[1].id, films[2].id]
    saved = await social.set_favourites(session, anya.id, chosen)
    assert [film.id for film in saved] == chosen

    with pytest.raises(SocialError, match="помещается"):
        await social.set_favourites(session, anya.id, [f.id for f in films])


async def test_favourites_can_be_reordered(session):
    """Перестановка не должна спотыкаться об уникальность позиции."""
    anya, _ = await two_people(session)
    films = [await make_film(session, f"Фильм {i}") for i in range(3)]
    await session.commit()

    await social.set_favourites(session, anya.id, [f.id for f in films])
    swapped = await social.set_favourites(session, anya.id, [films[2].id, films[1].id, films[0].id])

    assert [film.id for film in swapped] == [films[2].id, films[1].id, films[0].id]


async def test_favourites_reject_duplicates_and_unknown_films(session):
    anya, _ = await two_people(session)
    film = await make_film(session, "Фильм")
    await session.commit()

    with pytest.raises(SocialError, match="повторяются"):
        await social.set_favourites(session, anya.id, [film.id, film.id])
    with pytest.raises(SocialError, match="не найден"):
        await social.set_favourites(session, anya.id, [999999])


async def test_feed_collects_marks_ratings_and_watches(session):
    """Лента собирается из событий, которые и так есть, — новых записей нет."""
    _, films, screening, _, voters = await held_screening(session)
    watcher = voters[0]
    await add_interest(session, watcher, films[1], InterestKind.SOON, 0)
    await att.save_feedback(
        session, screening.id, watcher.id, film_rating=8, review_text="Хорошо", org=None
    )

    items = await social.feed(session, [watcher.id])

    assert {item.kind for item in items} >= {"soon", "rating"}
    rating = next(item for item in items if item.kind == "rating")
    assert rating.rating == 8
    assert rating.text == "Хорошо"
    assert rating.film_title == films[0].title_ru


async def test_feed_of_nobody_is_empty(session):
    assert await social.feed(session, []) == []


async def test_profile_counts_what_the_person_did(session):
    _, films, screening, _, voters = await held_screening(session)
    watcher, viewer = voters[0], voters[1]
    await add_interest(session, watcher, films[1], InterestKind.WISHLIST, 0)
    await att.save_feedback(
        session, screening.id, watcher.id, film_rating=9, review_text=None, org=None
    )
    await social.set_favourites(session, watcher.id, [films[0].id])

    profile = await social.profile(session, viewer.id, watcher.id)

    assert profile.display_name == watcher.display_name
    assert profile.marks == 1
    assert profile.watched == 1  # приход на показ засчитан просмотром
    assert profile.ratings == 1
    assert profile.average_rating == 9.0
    assert [f.id for f in profile.favourites] == [films[0].id]
    assert profile.relation.following is False


async def test_profile_of_unknown_person_is_none(session):
    anya, _ = await two_people(session)
    assert await social.profile(session, anya.id, 999999) is None


# --- через HTTP -------------------------------------------------------------


async def test_friend_flow_over_http(client, session):
    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    other = await login(client, 777401, "Сосед")
    headers = {"Authorization": f"Bearer {me['token']}"}
    other_headers = {"Authorization": f"Bearer {other['token']}"}
    other_id = other["user"]["id"]

    added = await client.post(f"/api/users/{other_id}/friend", headers=headers)
    assert added.status_code == 200
    assert added.json()["following"] is True
    assert added.json()["friends"] is False

    back = await client.post(
        f"/api/users/{me['user']['id']}/friend", headers=other_headers
    )
    assert back.json()["friends"] is True

    circle = (await client.get("/api/me/circle", headers=headers)).json()
    assert [person["display_name"] for person in circle["friends"]] == ["Сосед"]

    removed = await client.delete(f"/api/users/{other_id}/friend", headers=headers)
    assert removed.json()["following"] is False
    assert removed.json()["follower"] is True


async def test_profile_and_favourites_over_http(client, session):
    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    headers = {"Authorization": f"Bearer {me['token']}"}
    film = await make_film(session, "Любимое")
    await session.commit()

    saved = await client.put(
        "/api/me/favourites", json={"film_ids": [film.id]}, headers=headers
    )
    assert saved.status_code == 200
    assert [row["title_ru"] for row in saved.json()] == ["Любимое"]

    profile = (await client.get(f"/api/users/{me['user']['id']}", headers=headers)).json()
    assert profile["is_me"] is True
    assert [row["title_ru"] for row in profile["favourites"]] == ["Любимое"]

    too_many = await client.put(
        "/api/me/favourites", json={"film_ids": [film.id] * 5}, headers=headers
    )
    assert too_many.status_code == 422


async def test_people_search_skips_yourself(client, session):
    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    await login(client, 777402, "Главный помощник")

    found = (
        await client.get(
            "/api/people?q=Главный", headers={"Authorization": f"Bearer {me['token']}"}
        )
    ).json()

    assert [person["display_name"] for person in found] == ["Главный помощник"]
