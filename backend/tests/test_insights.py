"""Статистика по одному фильму и по одному сеансу (§14).

Свод по клубу проверяется в test_analytics; здесь — разрезы, которые админ
открывает, когда спрашивает «почему этот фильм» и «кто придёт».
"""

import sqlalchemy as sa

from app.models import Confirmation, Hall
from app.models.enums import ConfirmationState, InterestKind, ScreeningStatus
from app.services import attendance as att
from app.services import insights
from app.services import schedule as sched
from app.services.settings import SettingsService
from app.services.weights import WeightParams
from tests.test_analytics import held_screening
from tests.test_schedule import voted_round
from tests.test_weights import add_interest, make_film, make_user


async def params_of(session) -> WeightParams:
    return WeightParams.from_settings(await SettingsService(session).all())


async def test_film_stats_counts_marks_by_kind(session):
    film = await make_film(session, "Фильм")
    fans = [await make_user(session, f"Зритель {i}") for i in range(3)]
    await session.commit()
    await add_interest(session, fans[0], film, InterestKind.SOON, 0)
    await add_interest(session, fans[1], film, InterestKind.WISHLIST, 0)
    # Отметка годовой давности — она и есть «давно ждут».
    await add_interest(session, fans[2], film, InterestKind.WISHLIST, 400)
    await session.commit()

    stats = await insights.film_stats(session, film.id, await params_of(session), 90)

    assert stats.soon_count == 1
    assert stats.wishlist_count == 2
    assert stats.long_wait_count == 1
    assert stats.weight > 0


async def test_film_stats_is_none_for_unknown_film(session):
    assert await insights.film_stats(session, 999999, await params_of(session), 90) is None


async def test_shortlist_misses_count_only_rounds_without_a_screening(session):
    """Фильм проходит по весам, а вечера ему не достаётся — это и есть сигнал."""
    # Все три фильма уже в шорт-листе цикла; вечер достаётся одному.
    round_, films, slots, boss, _ = await voted_round(session)
    await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)

    misses = await insights.shortlist_misses(session, [films[0].id, films[1].id])

    assert misses[films[0].id] == (0, 1)  # назначен
    assert misses[films[1].id] == (1, 0)  # остался без вечера


async def test_screening_stats_before_the_show(session):
    round_, films, slots, boss, voters = await voted_round(session, capacity=4)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)
    await sched.confirm(session, screening.id, voters[1].id)

    values = await SettingsService(session).all()
    stats = await insights.screening_stats(session, screening.id, values)

    assert stats.confirmed == 2
    assert stats.capacity == 4
    assert stats.fill_rate == 50.0
    assert stats.attended == []


async def test_waitlist_is_named_and_ordered(session):
    round_, films, slots, boss, voters = await voted_round(session, capacity=1)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    for voter in voters:
        await sched.confirm(session, screening.id, voter.id)

    stats = await insights.screening_stats(
        session, screening.id, await SettingsService(session).all()
    )

    assert stats.confirmed == 1
    assert [person.display_name for person in stats.waitlist] == [
        voters[1].display_name,
        voters[2].display_name,
    ]
    assert stats.waitlist[0].detail == "в очереди 1"


async def test_no_shows_are_named(session):
    """Поимённый список тех, кто подтвердил и не пришёл (§14)."""
    _, _, screening, _, voters = await held_screening(session)

    stats = await insights.screening_stats(
        session, screening.id, await SettingsService(session).all()
    )

    assert [p.display_name for p in stats.attended] == [voters[0].display_name]
    assert [p.display_name for p in stats.no_shows] == [voters[1].display_name]


async def test_late_cancel_is_counted_apart(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)
    # Окно поздней отмены заведомо шире, чем срок до показа.
    await sched.cancel(session, screening.id, voters[0].id, late_cancel_hours=24 * 365)

    stats = await insights.screening_stats(
        session, screening.id, await SettingsService(session).all()
    )

    assert stats.cancelled == 1
    assert stats.late_cancels == 1
    assert stats.confirmed == 0


async def test_low_attendance_warning_only_near_the_start(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    values = dict(await SettingsService(session).all())
    values["min_attendance"] = 10

    # Показ ещё далеко — предупреждать рано.
    values["early_warning_hours"] = 1
    far = await insights.screening_stats(session, screening.id, values)
    assert far.low_attendance_warning is False

    # А за неделю до него кворум уже виден.
    values["early_warning_hours"] = 24 * 30
    close = await insights.screening_stats(session, screening.id, values)
    assert close.low_attendance_warning is True


async def test_screening_history_carries_actual_attendance(session):
    _, films, screening, _, _ = await held_screening(session)

    history = (await insights.screening_history(session, [films[0].id]))[films[0].id]

    assert len(history) == 1
    assert history[0].screening_id == screening.id
    assert history[0].expected == 3
    assert history[0].came == 1
    assert history[0].status == ScreeningStatus.COMPLETED


async def test_org_rating_is_separate_from_the_film(session):
    """§8: оценка организации в рейтинг фильма не входит."""
    _, _, screening, _, voters = await held_screening(session)
    await att.save_feedback(
        session,
        screening.id,
        voters[0].id,
        film_rating=9,
        review_text=None,
        org={"sound": 3, "picture": 3, "hall": 5, "time": 5},
    )

    stats = await insights.screening_stats(
        session, screening.id, await SettingsService(session).all()
    )

    assert stats.film_rating == 9.0
    assert stats.film_rating_votes == 1
    assert stats.org_rating == 4.0
    assert stats.org_rating_votes == 4


async def test_stats_of_unknown_screening_is_none(session):
    assert (
        await insights.screening_stats(session, 999999, await SettingsService(session).all())
    ) is None


async def test_capacity_zero_does_not_divide_by_zero(session):
    round_, films, slots, boss, _ = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    hall = (await session.execute(sa.select(Hall))).scalars().first()
    hall.capacity = 0
    await session.commit()

    stats = await insights.screening_stats(
        session, screening.id, await SettingsService(session).all()
    )
    assert stats.fill_rate == 0.0


async def test_confirmation_states_do_not_leak_into_each_other(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    session.add(
        Confirmation(
            screening_id=screening.id, user_id=voters[0].id, state=ConfirmationState.CANCELLED
        )
    )
    await session.commit()

    stats = await insights.screening_stats(
        session, screening.id, await SettingsService(session).all()
    )
    assert stats.confirmed == 0
    assert stats.cancelled == 1
    assert stats.no_shows == []
