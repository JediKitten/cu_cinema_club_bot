"""Ачивки: ступени, замена низшей на высшую, секретные (расширение по просьбе клуба)."""

import sqlalchemy as sa

from app.models import Achievement, Favourite, Notification
from app.models.enums import NotificationKind
from app.services import achievements, ratings, social, tournaments
from app.services.achievements import Tier
from tests.test_analytics import held_screening
from tests.test_tournaments import admin as tournament_admin
from tests.test_tournaments import close_current_round, matches_of_round, options
from tests.test_weights import make_film, make_user


async def rate_films(session, user, count: int) -> None:
    for index in range(count):
        film = await make_film(session, f"Фильм {user.id}-{index}")
        await session.commit()
        await ratings.set_rating(session, user.id, film.id, 4)


async def test_ladder_gives_the_badge_and_congratulates(session):
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 5)

    assert await achievements.award(session) == 1

    codes = (
        (await session.execute(sa.select(Achievement.code).where(Achievement.user_id == user.id)))
        .scalars()
        .all()
    )
    assert codes == ["ratings_bronze"]

    payload = (
        await session.execute(
            sa.select(Notification.payload).where(
                Notification.user_id == user.id,
                Notification.kind == NotificationKind.ACHIEVEMENT_EARNED,
            )
        )
    ).scalar_one()
    assert payload["title"] == "Появилось своё мнение..."
    assert payload["tier"] == "бронзовая"


async def test_higher_tier_replaces_the_lower_one(session):
    """Ачивка той же цели заменяется на значок получше, а не копится рядом."""
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 5)
    await achievements.award(session)

    await rate_films(session, user, 20)  # всего 25 — серебро
    await achievements.award(session)

    codes = (
        (await session.execute(sa.select(Achievement.code).where(Achievement.user_id == user.id)))
        .scalars()
        .all()
    )
    assert codes == ["ratings_silver"]

    summary = await achievements.of_user(session, user.id)
    assert summary.bronze == 0
    assert summary.silver == 1


async def test_jumping_over_a_tier_gives_only_the_higher_one(session):
    """Набрал сразу на серебро — получает серебро, а не две ачивки подряд."""
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 25)

    assert await achievements.award(session) == 1

    codes = (
        (await session.execute(sa.select(Achievement.code).where(Achievement.user_id == user.id)))
        .scalars()
        .all()
    )
    assert codes == ["ratings_silver"]


async def test_award_is_idempotent(session):
    """Фоновая задача выполняется много раз и не должна поздравлять дважды (§17)."""
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 5)

    assert await achievements.award(session) == 1
    assert await achievements.award(session) == 0
    assert await achievements.award(session) == 0


async def test_progress_points_at_the_next_tier(session):
    """«Осталось три до серебра» превращает награду в цель."""
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 7)
    await achievements.award(session)

    summary = await achievements.of_user(session, user.id)
    goal = next(item for item in summary.groups if item.group == "ratings")

    assert goal.tier == Tier.BRONZE
    assert goal.title == "Появилось своё мнение..."
    assert goal.next_title == "Готов высказаться"
    assert (goal.progress, goal.target) == (7, 25)


async def test_four_numbers_count_goals_not_badges(session):
    """В профиле четыре числа — по одному на уровень, и цель считается один раз."""
    _, _, _, _, voters = await held_screening(session)
    user = voters[0]
    await rate_films(session, user, 5)
    await achievements.award(session)

    summary = await achievements.of_user(session, user.id)

    # Бронза за оценки и бронза за первый сеанс — две разные цели.
    assert summary.bronze == 2
    assert summary.silver == summary.gold == summary.platinum == 0


async def test_secret_stays_hidden_until_it_is_found(session):
    """У секретной не видно ни названия, ни условия — только счётчик."""
    user = await make_user(session, "Зритель")
    films = [await make_film(session, f"Любимый {i}") for i in range(4)]
    await session.commit()

    before = await achievements.of_user(session, user.id)
    assert before.secrets_left == 3
    assert all(item.secret is False for item in before.groups)

    for position, film in enumerate(films):
        session.add(Favourite(user_id=user.id, film_id=film.id, position=position))
    await session.commit()
    await achievements.award(session)

    after = await achievements.of_user(session, user.id)
    assert after.secrets_left == 2
    found = next(item for item in after.groups if item.group == "showcase")
    assert found.title == "Витрина собрана"
    assert found.tier == Tier.SILVER


async def test_friends_badge_counts_outgoing_subscriptions(session):
    """«Добавить в друзья» — это подписка: взаимность зависит не от тебя."""
    user = await make_user(session, "Зритель")
    other = await make_user(session, "Сосед")
    await session.commit()
    await social.follow(session, user.id, other.id)

    await achievements.award(session)
    summary = await achievements.of_user(session, user.id)

    friends = next(item for item in summary.groups if item.group == "friends")
    assert friends.tier == Tier.BRONZE
    # У того, на кого подписались, ачивки нет: он ничего не сделал.
    theirs = await achievements.of_user(session, other.id)
    assert all(item.tier is None for item in theirs.groups)


async def test_champion_needs_every_pick_right(session):
    """«Абсолютный чемпион» — все выборы в пользу победителя, во всех парах."""
    boss = await tournament_admin(session)
    sharp = await make_user(session, "Провидец")
    sloppy = await make_user(session, "Угадал половину")
    await session.commit()

    tournament = await tournaments.create(session, boss.id, "Лучший злодей")
    await tournaments.set_options(session, tournament, options(4))
    await tournaments.start(session, tournament, boss.id)

    # Полуфинал: оба голосуют, но по-разному.
    semis = await matches_of_round(session, tournament, 1)
    for match in semis:
        await tournaments.vote(session, tournament, match.id, sharp.id, match.option_a_id)
        await tournaments.vote(session, tournament, match.id, sloppy.id, match.option_a_id)
    # Один голос неудачника — за того, кто не пройдёт.
    await tournaments.vote(session, tournament, semis[0].id, sloppy.id, semis[0].option_b_id)

    await close_current_round(session, tournament)
    await tournaments.tick(session)

    final = (await matches_of_round(session, tournament, 2))[0]
    await tournaments.vote(session, tournament, final.id, sharp.id, final.option_a_id)
    await tournaments.vote(session, tournament, final.id, sloppy.id, final.option_a_id)
    await close_current_round(session, tournament)
    await tournaments.tick(session)

    await achievements.award(session)

    champion = await achievements.of_user(session, sharp.id)
    assert any(item.group == "champion" and item.tier == Tier.GOLD for item in champion.groups)

    missed = await achievements.of_user(session, sloppy.id)
    assert all(item.group != "champion" for item in missed.groups)
    assert missed.secrets_left == 3


async def test_inactive_person_is_not_congratulated(session):
    """Отключённому аккаунту ачивки не начисляются: он уже не в клубе."""
    user = await make_user(session, "Ушёл")
    await session.commit()
    await rate_films(session, user, 5)
    user.is_active = False
    await session.commit()

    assert await achievements.award(session) == 0


async def test_summary_rides_along_with_the_profile(session):
    """Сводка приезжает вместе с профилем — отдельного запроса за ней нет."""
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 5)
    await achievements.award(session)

    profile = await social.profile(session, user.id, user.id)

    assert profile.achievements.bronze == 1
    assert profile.achievements.secrets_left == 3
