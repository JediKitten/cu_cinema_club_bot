"""Аналитика и воронка (§14)."""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.models import Slot
from app.models.enums import InterestKind, ScreeningStatus, UserRole
from app.services import analytics
from app.services import attendance as att
from app.services import interests as marks
from app.services import schedule as sched
from app.services.settings import SettingsService
from app.services.weights import WeightParams
from tests.test_schedule import voted_round
from tests.test_weights import add_interest, make_film, make_user


async def summary(session, long_wait_days: int = 90):
    """Сводка считает и веса — коэффициенты берём из тех же параметров §13."""
    params = WeightParams.from_settings(await SettingsService(session).all())
    return await analytics.overview(session, long_wait_days, params)


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

    overview = await summary(session)
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

    overview = await summary(session)
    assert overview.late_cancels == 1


async def test_cancelled_screenings_counted_separately(session):
    round_, films, slots, boss, _ = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.cancel_screening(session, screening.id, "не смогли", boss.id)

    overview = await summary(session)
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
    await att.save_feedback(session, screening.id, voters[0].id, 9, None)

    assert await analytics.top_rated(session, min_votes=5) == []

    listed = await analytics.top_rated(session, min_votes=1)
    assert listed[0]["title"] == films[0].title_ru
    # Оценка из формы после показа — тот же рейтинг клуба: девять из десяти
    # это 4,5 звезды из пяти.
    assert listed[0]["rating"] == 4.5


async def test_attendance_by_weekday(session):
    _, _, screening, _, _ = await held_screening(session)
    slot = await session.get(Slot, screening.slot_id)

    overview = await summary(session)
    weekday = analytics.WEEKDAYS[slot.starts_at.weekday()]
    assert overview.by_weekday[weekday] == 1.0


async def test_past_screenings_exclude_cancelled(session):
    """Отменённый показ никто не смотрел — в истории клуба ему не место."""
    round_, films, slots, boss, _ = await voted_round(session)
    cancelled = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.cancel_screening(session, cancelled.id, "не смогли", boss.id)

    assert await analytics.past_screenings(session) == []

    # А в аналитике отмена видна отдельно.
    overview = await summary(session)
    assert overview.screenings_cancelled == 1


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
    overview = await summary(session)

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

    overview = await summary(session)
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


async def test_came_counts_people_not_pairs_of_attendance_and_feedback(session):
    """«Пришли» не должно расти от числа отзывов.

    Отметки о приходе и отзывы висят на одном screening_id: соединённые
    в одном запросе, они перемножаются, и показ с двумя зрителями и двумя
    отзывами показывает четверых. Ошибка тихая — цифра просто красивее.
    """
    _, _, screening, boss, voters = await held_screening(session)
    # Второй зритель тоже дошёл, и оба оставили отзыв.
    await att.mark_manually(session, screening.id, voters[1].id, boss.id)
    for voter in voters[:2]:
        await att.save_feedback(session, screening.id, voter.id, 8, None)

    row = next(
        r for r in await analytics.past_screenings(session) if r["screening_id"] == screening.id
    )

    assert row["came"] == 2
    assert row["rating"] == 8.0


async def test_audience_by_week_counts_people_not_actions(session):
    """Один человек, четыре действия за неделю — это один активный человек."""
    _, _, _, _, voters = await held_screening(session)

    weeks = await analytics.audience_by_week(session)

    assert weeks, "неделя с активностью должна быть видна"
    assert all(point["people"] <= len(voters) + 1 for point in weeks)


async def test_no_show_users_names_the_repeat_offenders(session):
    _, _, _, _, voters = await held_screening(session)

    offenders = await analytics.no_show_users(session)

    # Подтвердили двое, пришёл один — в списке ровно второй.
    assert [row["display_name"] for row in offenders] == [voters[1].display_name]
    assert offenders[0]["misses"] == 1


async def test_soon_churn_counts_those_who_did_not_come_back(session):
    """Срок «Ближайшего» вышел, новой отметки нет — человек собирался и пропал."""
    film = await make_film(session, "Фильм")
    lapsed = await make_user(session, "Пропал")
    active = await make_user(session, "Вернулся")
    other = await make_film(session, "Другой")
    await session.commit()

    await add_interest(session, lapsed, film, InterestKind.SOON, 30)
    await add_interest(session, active, film, InterestKind.SOON, 30)
    # У второго есть и свежая отметка — он никуда не делся.
    await add_interest(session, active, other, InterestKind.SOON, 1)
    await session.commit()

    churn = await analytics.soon_churn(
        session, WeightParams.from_settings(await SettingsService(session).all())
    )

    assert churn["expired_marks"] == 2
    assert churn["people"] == 2
    assert churn["lapsed"] == 1


async def test_cancelled_share_is_a_percentage(session):
    _, _, screening, boss, _ = await held_screening(session)
    screening.status = ScreeningStatus.CANCELLED
    await session.commit()

    assert (await summary(session)).cancelled_share == 100.0


async def test_csat_by_week_combines_evening_and_discussion(session):
    """Общий CSAT — из вечера и обсуждения, не из фильма. Кто на обсуждении
    не был, у того общий — это вечер: пропуск не тянет цифру ни вверх, ни вниз."""
    from zoneinfo import ZoneInfo

    _, _, screening, _, voters = await held_screening(session)
    await att.mark_manually(session, screening.id, voters[1].id, voters[1].id)
    await att.save_feedback(
        session, screening.id, voters[0].id,
        film_rating=2, review_text=None, visit_rating=8, discussion_rating=10,
    )
    await att.save_feedback(
        session, screening.id, voters[1].id,
        film_rating=2, review_text=None, visit_rating=6, discussion_skip="absent",
    )

    weeks = await analytics.csat_by_week(session)

    assert len(weeks) == 1
    week = weeks[0]
    slot = await session.get(Slot, screening.slot_id)
    local = slot.starts_at.astimezone(ZoneInfo("Europe/Moscow")).date()
    # Неделя — по дате показа, в часовом поясе клуба.
    assert week.week_start == local - timedelta(days=local.weekday())
    # Первый: (4 + 5) / 2 = 4,5 звезды; второй: только вечер — 3. Среднее — 3,75.
    # Фильм на единицу не влияет ни на что.
    assert week.overall == 3.75 and week.overall_votes == 2
    assert week.visit == 3.5 and week.visit_votes == 2
    assert week.discussion == 5.0 and week.discussion_votes == 1


async def test_csat_by_week_is_in_the_analytics_response(client, session):
    from tests.conftest import SUPERADMIN_TG_ID, login

    _, _, screening, _, voters = await held_screening(session)
    await att.save_feedback(
        session, screening.id, voters[0].id,
        film_rating=None, review_text=None, visit_rating=10, discussion_rating=None,
    )
    auth = await login(client, SUPERADMIN_TG_ID, "Главный")
    response = await client.get(
        "/api/admin/analytics", headers={"Authorization": f"Bearer {auth['token']}"}
    )

    assert response.status_code == 200, response.text
    [week] = response.json()["overview"]["csat_by_week"]
    assert week["overall"] == 5.0 and week["discussion"] is None


async def test_rankings_survive_a_film_with_past_screenings(client, session):
    """У фильма в рейтинге есть прошедший показ — рейтинги обязаны отдаться.

    История показов шла словарём с ключом `expected_attendance`, а схема
    ответа ждёт `expected`: после ужесточения схем рейтинги падали с 500,
    и админка молча показывала «Фильмы · 0» — шорт-лист было не собрать.
    """
    from tests.conftest import SUPERADMIN_TG_ID, login
    from tests.test_weights import add_interest

    _, films, screening, _, voters = await held_screening(session)
    await add_interest(session, voters[2], films[0], InterestKind.WISHLIST)
    await session.commit()

    auth = await login(client, SUPERADMIN_TG_ID, "Главный")
    response = await client.get(
        "/api/admin/rankings", headers={"Authorization": f"Bearer {auth['token']}"}
    )

    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["by_weight"] if r["film_id"] == films[0].id)
    [record] = row["screening_history"]
    assert record["screening_id"] == screening.id
    assert record["expected"] == screening.expected_attendance

    # Та же история в разрезе по фильму — второй путь к той же схеме.
    stats = await client.get(
        f"/api/admin/films/{films[0].id}/stats",
        headers={"Authorization": f"Bearer {auth['token']}"},
    )
    assert stats.status_code == 200, stats.text
    assert stats.json()["history"][0]["expected"] == screening.expected_attendance
