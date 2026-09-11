"""Ачивки: ступени, замена низшей на высшую, секретные (расширение по просьбе клуба)."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Achievement, Favourite, Notification
from app.models.enums import InterestKind, NotificationKind
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
    assert payload["title"] == "Появилось свое мнение..."
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
    assert goal.title == "Появилось свое мнение..."
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
    assert sum(before.secrets_left.values()) == 3
    # Счётчик стоит на уровне секретной: пустая вкладка иначе необъяснима.
    assert before.secrets_left == {"silver": 1, "gold": 1, "platinum": 1}
    assert all(item.secret is False for item in before.groups)

    for position, film in enumerate(films):
        session.add(Favourite(user_id=user.id, film_id=film.id, position=position))
    await session.commit()
    await achievements.award(session)

    after = await achievements.of_user(session, user.id)
    assert sum(after.secrets_left.values()) == 2
    assert "silver" not in after.secrets_left
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
    assert sum(missed.secrets_left.values()) == 3


async def test_english_screenings_are_counted_separately(session):
    """«Сеансы на английском» — свойство сеанса, а не фильма.

    Один и тот же фильм клуб может показать и с дубляжом, и в оригинале,
    поэтому считается приход именно на помеченный показ.
    """
    from app.models import Screening
    from app.services import attendance as att
    from app.services import events

    boss = await make_user(session, "Админ")
    guest = await make_user(session, "Зритель")
    film = await make_film(session, "Pulp Fiction")
    await session.commit()

    usual = await events.create(
        session, starts_at=datetime.now(UTC) + timedelta(days=1), actor_id=boss.id, film_id=film.id
    )
    english = await events.create(
        session,
        starts_at=datetime.now(UTC) + timedelta(days=2),
        actor_id=boss.id,
        title="Кино в оригинале",
        in_english=True,
    )
    await att.mark_manually(session, usual.id, guest.id, boss.id)
    await att.mark_manually(session, english.id, guest.id, boss.id)

    assert (await session.get(Screening, english.id)).in_english is True

    counts = (await achievements.metrics(session, [guest.id])).get(guest.id, {})
    assert counts["attended"] == 2  # сеансов было два
    assert counts["english"] == 1  # а на английском — один


async def test_referrals_count_only_those_who_agreed(session):
    """Позвал — это не переход по ссылке, а согласие: отметка после перехода."""
    from app.services import interests, referrals

    host = await make_user(session, "Позвал")
    came = await make_user(session, "Пришёл и отметил")
    passed_by = await make_user(session, "Посмотрел и ушёл")
    film = await make_film(session, "Крёстный отец")
    await session.commit()

    await referrals.record(session, host.id, came.id, film.id)
    await referrals.record(session, host.id, passed_by.id, film.id)
    await interests.set_mark(session, came.id, film.id, InterestKind.WISHLIST, 14, 10)

    counts = (await achievements.metrics(session, [host.id])).get(host.id, {})
    assert counts.get("referrals") == 1


async def test_congratulation_names_the_next_step(session):
    """Поздравление без «что дальше» сообщает только о конце."""
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 5)
    await achievements.award(session)

    payload = (
        await session.execute(
            sa.select(Notification.payload).where(
                Notification.user_id == user.id,
                Notification.kind == NotificationKind.ACHIEVEMENT_EARNED,
            )
        )
    ).scalar_one()

    assert payload["next_title"] == "Готов высказаться"
    assert payload["next_hint"] == "Оценить 25 фильмов"


async def test_top_tier_has_nothing_ahead(session):
    """У платины следующей ступени нет — и сообщение не должно её выдумывать."""
    ladder = achievements.LADDERS["ratings"]
    assert ladder[-1].tier == Tier.PLATINUM
    assert [rule.target for rule in ladder] == [5, 25, 100, 500]


async def test_goals_follow_the_order_of_the_club_table(session):
    """Порядок целей — как в таблице клуба, и он не пляшет от чужих отметок."""
    user = await make_user(session, "Зритель")
    await session.commit()

    summary = await achievements.of_user(session, user.id)

    assert [item.group for item in summary.groups] == [
        "films",
        "screenings",
        "english",
        "friends",
        "ratings",
        "referrals",
    ]


async def test_admin_grants_a_named_achievement(session):
    """Именная придумывается под человека — её правила в реестре быть не может."""
    boss = await make_user(session, "Админ")
    hero = await make_user(session, "Принёс проектор")
    await session.commit()

    row = await achievements.grant(
        session, boss.id, hero.id, "Спас показ", "Притащил проектор из дома", "gold"
    )

    summary = await achievements.of_user(session, hero.id)
    named = next(item for item in summary.groups if item.custom)

    assert named.title == "Спас показ"
    assert named.tier == Tier.GOLD
    assert summary.gold == 1  # считается в тех же четырёх числах
    # И человек об этом узнаёт.
    payload = (
        await session.execute(
            sa.select(Notification.payload).where(
                Notification.user_id == hero.id,
                Notification.kind == NotificationKind.ACHIEVEMENT_EARNED,
            )
        )
    ).scalar_one()
    assert payload["title"] == "Спас показ"
    assert payload["custom"] is True

    # Снять можно — в отличие от заслуженных автоматом.
    await achievements.revoke(session, boss.id, row.id)
    assert (await achievements.of_user(session, hero.id)).gold == 0


async def test_one_person_can_hold_several_named_achievements(session):
    """Код именной случайный: вторая не должна упираться в уникальность."""
    boss = await make_user(session, "Админ")
    hero = await make_user(session, "Двужильный")
    await session.commit()

    await achievements.grant(session, boss.id, hero.id, "Спас показ", "", "gold")
    await achievements.grant(session, boss.id, hero.id, "Спас второй", "", "silver")

    summary = await achievements.of_user(session, hero.id)
    assert len([item for item in summary.groups if item.custom]) == 2
    assert (summary.gold, summary.silver) == (1, 1)


async def test_named_achievement_needs_a_real_tier_and_title(session):
    boss = await make_user(session, "Админ")
    hero = await make_user(session, "Зритель")
    await session.commit()

    with pytest.raises(achievements.AchievementError, match="уровень"):
        await achievements.grant(session, boss.id, hero.id, "Что-то", "", "diamond")
    with pytest.raises(achievements.AchievementError, match="название"):
        await achievements.grant(session, boss.id, hero.id, "   ", "", "gold")


async def test_auto_achievements_cannot_be_revoked_by_hand(session):
    """Снимать заслуженное автоматом нельзя — иначе награда перестаёт быть наградой."""
    boss = await make_user(session, "Админ")
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 5)
    await achievements.award(session)

    earned = (
        await session.execute(sa.select(Achievement).where(Achievement.user_id == user.id))
    ).scalar_one()

    with pytest.raises(achievements.AchievementError, match="не найдена"):
        await achievements.revoke(session, boss.id, earned.id)


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
    assert sum(profile.achievements.secrets_left.values()) == 3
