"""Ачивки: ступени, замена низшей на высшую, секретные (расширение по просьбе клуба)."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Achievement, Favourite, Notification
from app.models.enums import InterestKind, NotificationKind
from app.services import achievements, notify, ratings, social, tournaments
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


async def test_higher_tier_takes_the_trophy_but_the_lower_one_keeps_burning(session):
    """Трофей у цели один — высший, но пройденная ступень остаётся взятой.

    Отбирать у человека бронзу за то, что он дорос до серебра, незачем:
    в своей вкладке она должна гореть с галочкой, а не выглядеть недостижимой.
    """
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 5)
    await achievements.award(session)

    await rate_films(session, user, 20)  # всего 25 — серебро
    await achievements.award(session)

    codes = sorted(
        (await session.execute(sa.select(Achievement.code).where(Achievement.user_id == user.id)))
        .scalars()
        .all()
    )
    assert codes == ["ratings_bronze", "ratings_silver"]

    summary = await achievements.of_user(session, user.id)
    # Обе ступени взяты — обе и светятся. Раньше числа считали цели, и бронза
    # под серебром гасла, хотя ачивка получена и никуда не делась.
    assert summary.bronze == 1
    assert summary.silver == 1

    goal = next(item for item in summary.groups if item.group == "ratings")
    assert goal.tier == Tier.SILVER
    passed = {step.tier: step.earned_at is not None for step in goal.steps}
    assert passed[Tier.BRONZE] is True
    assert passed[Tier.SILVER] is True
    assert passed[Tier.GOLD] is False


async def test_jumping_over_a_tier_congratulates_once(session):
    """Набрал сразу на серебро — одно поздравление, но бронза тоже пройдена.

    Три сообщения подряд за один рывок читаются как сбой, а не как награда.
    """
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 25)

    assert await achievements.award(session) == 1

    codes = sorted(
        (await session.execute(sa.select(Achievement.code).where(Achievement.user_id == user.id)))
        .scalars()
        .all()
    )
    assert codes == ["ratings_bronze", "ratings_silver"]

    told = (
        (
            await session.execute(
                sa.select(Notification.payload).where(
                    Notification.user_id == user.id,
                    Notification.kind == NotificationKind.ACHIEVEMENT_EARNED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [item["title"] for item in told] == ["Готов высказаться"]


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
    # Что дальше — только условием: название следующей ступени тоже сюрприз.
    assert goal.next_title is None
    assert goal.next_description == "Оценить 25 фильмов"
    assert (goal.progress, goal.target) == (7, 25)


async def test_four_numbers_count_every_badge_taken(session):
    """В профиле четыре числа — по одному на уровень, и считают они всё взятое."""
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
    assert found.title == "Choose your fighter"
    assert found.tier == Tier.SILVER


async def test_foreign_secret_is_a_trophy_without_a_name(session):
    """В чужом профиле секретная видна трофеем, но не названием.

    Иначе достаточно заглянуть к любому старожилу, чтобы узнать их все,
    и искать станет нечего.
    """
    from app.models import Favourite

    owner = await make_user(session, "Открыл")
    stranger = await make_user(session, "Не открыл")
    films = [await make_film(session, f"Любимый {i}") for i in range(4)]
    await session.commit()
    for position, film in enumerate(films):
        session.add(Favourite(user_id=owner.id, film_id=film.id, position=position))
    await session.commit()
    await achievements.award(session)

    # Сам владелец видит всё как есть.
    mine = await achievements.of_user(session, owner.id, viewer_id=owner.id)
    own = next(item for item in mine.groups if item.group == "showcase")
    assert own.title == "Choose your fighter"
    assert own.hidden is False

    # Посторонний — только трофей.
    theirs = await achievements.of_user(session, owner.id, viewer_id=stranger.id)
    masked = next(item for item in theirs.groups if item.group == "showcase")
    assert masked.hidden is True
    assert masked.title == achievements.HIDDEN_TITLE
    assert "Выбрать 4 любимых" not in masked.description
    # Трофей при этом засчитан — он не секрет.
    assert masked.tier == Tier.SILVER
    assert theirs.silver == 1
    # И в ступенях условия тоже нет.
    assert all(step.title == achievements.HIDDEN_TITLE for step in masked.steps)


async def test_shared_secret_is_visible_to_the_one_who_also_found_it(session):
    """Открывшему ту же секретную скрывать нечего — он и так знает, что это."""
    from app.models import Favourite

    people = [await make_user(session, f"Знаток {i}") for i in range(2)]
    films = [await make_film(session, f"Любимый {i}") for i in range(4)]
    await session.commit()
    for person in people:
        for position, film in enumerate(films):
            session.add(Favourite(user_id=person.id, film_id=film.id, position=position))
    await session.commit()
    await achievements.award(session)

    theirs = await achievements.of_user(session, people[0].id, viewer_id=people[1].id)
    shown = next(item for item in theirs.groups if item.group == "showcase")

    assert shown.hidden is False
    assert shown.title == "Choose your fighter"


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


async def test_congratulation_says_what_is_next_without_naming_it(session):
    """Поздравление без «что дальше» сообщает только о конце. Но и название
    следующей ступени не выдаёт: в профиле оно скрыто до получения, и портить
    сюрприз единственным местом было бы странно."""
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

    assert "next_title" not in payload
    assert payload["next_hint"] == "Оценить 25 фильмов"

    text = notify.render(NotificationKind.ACHIEVEMENT_EARNED, None, "", payload)
    assert text is not None
    assert "оценить 25 фильмов" in text.lower() and "Готов высказаться" not in text
    # За что дали — условие полученной ступени, а не следующей. Раньше
    # шаблон затирал одно другим, и 142 поздравления в бою сообщили
    # «бронзовая ачивка — Оценить 25 фильмов» за пять оценок.
    assert "ачивка — Оценить 5 фильмов" in text


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


async def test_secret_achievement_says_it_was_secret(session):
    """Секретную человек не искал и о ней не знал.

    Без этого поздравление выглядит обычной ступенью, которую он и так бы
    взял, — и весь смысл секретной теряется в момент выдачи.
    """
    from app.models import Favourite
    from app.services.notify import render

    user = await make_user(session, "Нашёл")
    films = [await make_film(session, f"Любимый {i}") for i in range(4)]
    await session.commit()
    for position, film in enumerate(films):
        session.add(Favourite(user_id=user.id, film_id=film.id, position=position))
    await session.commit()

    await achievements.award(session)

    payload = (
        await session.execute(
            sa.select(Notification.payload).where(
                Notification.user_id == user.id,
                Notification.kind == NotificationKind.ACHIEVEMENT_EARNED,
            )
        )
    ).scalar_one()
    assert payload["secret"] is True

    text = render(NotificationKind.ACHIEVEMENT_EARNED, None, "", payload)
    assert "Секретное достижение" in text
    assert "Choose your fighter" in text
    # «Дальше» у секретной нет: ступень у неё одна.
    assert "Дальше" not in text


async def test_named_achievement_does_not_promise_a_next_step(session):
    """У именной следующей ступени нет — и сообщение не должно её выдумывать."""
    from app.services.notify import render

    boss = await make_user(session, "Админ")
    hero = await make_user(session, "Герой")
    await session.commit()
    await achievements.grant(session, boss.id, hero.id, "Спас показ", "Принёс проектор", "gold")

    payload = (
        await session.execute(
            sa.select(Notification.payload).where(Notification.user_id == hero.id)
        )
    ).scalar_one()
    text = render(NotificationKind.ACHIEVEMENT_EARNED, None, "", payload)

    assert "лично" in text
    assert "верхняя ступень" not in text


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


async def test_name_of_an_unearned_badge_is_a_surprise(session):
    """Название до получения скрыто, условие — нет.

    Знать, что делать, человек должен; как это назовут — приятнее узнать
    в момент выдачи. Пряталось раньше только секретное, и весь список ступеней
    читался как оглавление.
    """
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 5)
    await achievements.award(session)

    goal = next(
        item
        for item in (await achievements.of_user(session, user.id)).groups
        if item.group == "ratings"
    )
    taken = next(step for step in goal.steps if step.tier == Tier.BRONZE)
    ahead = next(step for step in goal.steps if step.tier == Tier.SILVER)

    assert taken.title == "Появилось свое мнение..." and taken.done
    assert ahead.title == "" and not ahead.done
    # Условие остаётся: без него непонятно, что делать.
    assert ahead.description == "Оценить 25 фильмов"
    assert (ahead.progress, ahead.target) == (5, 25)


async def test_no_badge_names_leak_through_the_ladder(session):
    """Ни одного названия неполученной ступени — ни в одной цели."""
    user = await make_user(session, "Новичок")
    await session.commit()

    summary = await achievements.of_user(session, user.id)
    names = {
        step.title
        for item in summary.groups
        for step in item.steps
        if step.earned_at is None
    }
    assert names == {""}


async def test_a_missing_lower_step_is_filled_in_later(session):
    """Дырки от старого поведения должны зарастать сами.

    Когда-то высшая ступень стирала низшую, и у людей осталось серебро без
    бронзы — одно из четырёх чисел в профиле недосчитывалось. Цель с уже
    взятым верхом пропускалась целиком, и починить это было некому.
    """
    user = await make_user(session, "Зритель")
    await session.commit()
    await rate_films(session, user, 25)
    await achievements.award(session)

    # Воспроизводим старую беду: бронзы нет, серебро есть.
    await session.execute(
        sa.delete(Achievement).where(
            Achievement.user_id == user.id, Achievement.code == "ratings_bronze"
        )
    )
    await session.commit()
    assert (await achievements.of_user(session, user.id)).bronze == 0

    await achievements.award(session)

    summary = await achievements.of_user(session, user.id)
    assert summary.bronze == 1 and summary.silver == 1
    # И без второго поздравления: серебро человек взял давно.
    assert (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.kind == NotificationKind.ACHIEVEMENT_EARNED,
            )
        )
    ) == 1
