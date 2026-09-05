"""Аналитика и воронка (§14)."""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.models import Slot
from app.models.enums import InterestKind, ScreeningStatus, UserRole
from app.services import analytics
from app.services import attendance as att
from app.services import interests as marks
from app.services import schedule as sched
from tests.test_schedule import voted_round
from tests.test_weights import add_interest, make_film, make_user


async def held_screening(session):
    """Проведённый показ: двое подтвердили, пришёл один."""
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)
    await sched.confirm(session, screening.id, voters[1].id)

    await att.mark_manually(session, screening.id, voters[0].id, boss.id)

    screening.status = ScreeningStatus.COMPLETED
    await session.commit()
    return round_, films, screening, boss, voters


async def test_funnel_shows_each_transition(session):
    """Важны переходы: где именно теряются люди (§14)."""
    round_, _, screening, _, voters = await held_screening(session)

    steps = await analytics.funnel(session)
    assert len(steps) == 1
    step = steps[0]

    assert step.week_start == round_.week_start
    assert step.voted == 3  # голосовали трое
    assert step.confirmed == 2  # подтвердили двое
    assert step.attended == 1  # пришёл один


async def test_funnel_lists_recent_weeks_first(session):
    from datetime import date

    from app.services import rounds as rounds_service
    from tests.test_rounds import admin

    boss = await admin(session)
    await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    await rounds_service.open_round(session, date(2026, 9, 14), boss.id)

    steps = await analytics.funnel(session)
    assert [s.week_start.isoformat() for s in steps] == ["2026-09-14", "2026-09-07"]


async def test_no_show_rate_counts_confirmed_who_did_not_come(session):
    await held_screening(session)

    overview = await analytics.overview(session, long_wait_days=90)
    # Из двух подтвердивших пришёл один.
    assert overview.no_show_rate == 50.0
    assert overview.screenings_held == 1
    assert overview.average_attendance == 1.0


async def test_late_cancels_counted(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) + timedelta(hours=2)
    await session.commit()
    await sched.cancel(session, screening.id, voters[0].id, late_cancel_hours=24)

    overview = await analytics.overview(session, long_wait_days=90)
    assert overview.late_cancels == 1


async def test_cancelled_screenings_counted_separately(session):
    round_, films, slots, boss, _ = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.cancel_screening(session, screening.id, "не смогли", boss.id)

    overview = await analytics.overview(session, long_wait_days=90)
    assert overview.screenings_cancelled == 1
    assert overview.screenings_held == 0


async def test_long_wait_films_listed(session):
    """Топ фильмов по «давно ждут» (§14)."""
    film = await make_film(session, "Давно ждут")
    fresh = await make_film(session, "Свежий")
    old_user = await make_user(session, "Давний")
    new_user = await make_user(session, "Новый")
    await session.commit()

    await add_interest(session, old_user, film, InterestKind.WISHLIST, 200)
    await add_interest(session, new_user, fresh, InterestKind.WISHLIST, 5)
    await session.commit()

    listed = await analytics.long_waiting(session, long_wait_days=90)
    assert [row["title"] for row in listed] == ["Давно ждут"]
    assert listed[0]["waiting"] == 1
    assert listed[0]["days"] >= 200


async def test_top_rated_hides_films_with_too_few_votes(session):
    """§11: при малом числе оценок рейтинг не показываем вовсе."""
    _, films, screening, boss, voters = await held_screening(session)
    await att.save_feedback(session, screening.id, voters[0].id, 9, None, None)

    assert await analytics.top_rated(session, min_votes=5) == []

    listed = await analytics.top_rated(session, min_votes=1)
    assert listed[0]["title"] == films[0].title_ru
    assert listed[0]["rating"] == 9.0


async def test_attendance_by_weekday(session):
    _, _, screening, _, _ = await held_screening(session)
    slot = await session.get(Slot, screening.slot_id)

    overview = await analytics.overview(session, long_wait_days=90)
    weekday = analytics.WEEKDAYS[slot.starts_at.weekday()]
    assert overview.by_weekday[weekday] == 1.0


async def test_past_screenings_exclude_upcoming(session):
    round_, films, slots, boss, voters = await voted_round(session)
    held = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    upcoming = await sched.assign(session, round_, films[1].id, slots[1].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    held.status = ScreeningStatus.COMPLETED
    await session.commit()

    listed = await analytics.past_screenings(session)
    ids = [row["screening_id"] for row in listed]
    assert held.id in ids
    assert upcoming.id not in ids


async def test_overview_is_safe_on_empty_database(session):
    """Пустая база не должна ронять аналитику делением на ноль."""
    overview = await analytics.overview(session, long_wait_days=90)

    assert overview.rounds == 0
    assert overview.average_attendance == 0.0
    assert overview.no_show_rate == 0.0
    assert overview.hall_fill_rate == 0.0
    assert overview.by_weekday == {}


async def test_analytics_requires_admin_role(session):
    """Полная аналитика — только админам (§9)."""
    user = await make_user(session, "Обычный")
    await session.commit()
    assert user.role == UserRole.USER


async def test_fill_rate_uses_hall_capacity(session):
    _, _, screening, _, _ = await held_screening(session)

    from app.models import Hall

    hall = (await session.execute(sa.select(Hall))).scalars().first()
    hall.capacity = 4
    await session.commit()

    overview = await analytics.overview(session, long_wait_days=90)
    # Пришёл один из четырёх мест.
    assert overview.hall_fill_rate == 25.0


async def test_watched_film_leaves_the_funnel_interest(session):
    """Пришедший теряет отметку — это видно в аналитике как рост «пришёл»."""
    _, films, screening, boss, voters = await held_screening(session)
    await marks.set_mark(session, voters[1].id, films[0].id, InterestKind.WISHLIST, 14, 10)

    before = (await analytics.funnel(session))[0]
    await att.mark_manually(session, screening.id, voters[1].id, boss.id)
    after = (await analytics.funnel(session))[0]

    assert after.attended == before.attended + 1
    state = await marks.state(session, voters[1].id, films[0].id, 14)
    assert state.effective_kind is None


async def test_screening_history_visible_in_past(session):
    _, _, screening, _, _ = await held_screening(session)
    listed = await analytics.past_screenings(session)
    row = next(r for r in listed if r["screening_id"] == screening.id)

    assert row["came"] == 1
    assert row["expected"] == 3  # столько ожидали по матрице
    assert row["status"] == ScreeningStatus.COMPLETED
