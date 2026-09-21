"""Оценки фильмов участниками клуба (расширение по просьбе клуба)."""

import pytest
import sqlalchemy as sa

from app.models import FilmRating
from app.services import attendance as att
from app.services import ratings
from app.services.ratings import RatingError
from tests.conftest import SUPERADMIN_TG_ID, login
from tests.test_analytics import held_screening
from tests.test_weights import make_film, make_user


def test_stars_convert_to_half_points_without_drift():
    """В базе целые полубаллы, поэтому 4,5 остаётся 4,5, а не 4,4999."""
    assert ratings.to_score(4.5) == 9
    assert ratings.to_score(0.5) == 1
    assert ratings.to_score(5) == 10
    assert ratings.to_stars(9) == 4.5


def test_quarter_stars_are_rejected():
    with pytest.raises(RatingError, match="ползвезды"):
        ratings.to_score(4.25)


def test_zero_and_overflow_are_rejected():
    with pytest.raises(RatingError):
        ratings.to_score(0)
    with pytest.raises(RatingError):
        ratings.to_score(5.5)


async def test_rating_can_be_set_changed_and_removed(session):
    film = await make_film(session, "Фильм")
    viewer = await make_user(session, "Зритель")
    await session.commit()

    await ratings.set_rating(session, viewer.id, film.id, 4.5)
    assert await ratings.my_rating(session, viewer.id, film.id) == 4.5

    # Повторная оценка заменяет прежнюю, а не добавляет вторую.
    club = await ratings.set_rating(session, viewer.id, film.id, 3)
    assert club.average == 3.0
    assert club.votes == 1

    empty = await ratings.set_rating(session, viewer.id, film.id, None)
    assert empty.votes == 0
    assert await ratings.my_rating(session, viewer.id, film.id) is None


async def test_club_rating_is_the_average(session):
    film = await make_film(session, "Фильм")
    first = await make_user(session, "Первый")
    second = await make_user(session, "Второй")
    await session.commit()

    await ratings.set_rating(session, first.id, film.id, 5)
    club = await ratings.set_rating(session, second.id, film.id, 4)

    assert club.average == 4.5
    assert club.votes == 2


async def test_rating_an_unknown_film_fails(session):
    viewer = await make_user(session, "Зритель")
    await session.commit()

    with pytest.raises(ratings.FilmNotFound, match="не найден"):
        await ratings.set_rating(session, viewer.id, 999999, 5)


async def test_feedback_after_the_screening_feeds_the_same_rating(session):
    """Рейтинг у фильма один, откуда бы оценка ни пришла."""
    _, films, screening, _, voters = await held_screening(session)

    await att.save_feedback(session, screening.id, voters[0].id, 9, None)

    club = await ratings.summary(session, films[0].id)
    assert club.average == 4.5
    assert club.votes == 1
    stored = (
        await session.execute(sa.select(FilmRating).where(FilmRating.film_id == films[0].id))
    ).scalar_one()
    assert stored.source == "screening"


async def test_rating_over_http_shows_up_on_the_card(client, session):
    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    headers = {"Authorization": f"Bearer {me['token']}"}
    film = await make_film(session, "Оценённый")
    await session.commit()

    rated = await client.put(
        f"/api/films/{film.id}/rating", json={"stars": 3.5}, headers=headers
    )
    assert rated.status_code == 200
    assert rated.json()["internal_rating"] == 3.5
    assert rated.json()["internal_votes"] == 1

    card = (await client.get(f"/api/films/{film.id}", headers=headers)).json()
    assert card["my_rating"] == 3.5
    assert card["internal_rating"] == 3.5
    assert card["internal_votes"] == 1

    # Порог «показывать с пяти оценок» на карточке не действует: рядом стоит
    # число оценивших, и оно честнее порога.
    assert card["internal_votes"] == 1


async def test_quarter_star_is_refused_over_http(client, session):
    me = await login(client, SUPERADMIN_TG_ID, "Главный")
    film = await make_film(session, "Фильм")
    await session.commit()

    bad = await client.put(
        f"/api/films/{film.id}/rating",
        json={"stars": 4.25},
        headers={"Authorization": f"Bearer {me['token']}"},
    )
    assert bad.status_code == 422
