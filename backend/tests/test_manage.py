"""Ручные события и назначение ролей (§9, §10)."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Confirmation, Notification, Screening, Slot
from app.models.enums import ConfirmationState, ScreeningStatus, UserRole
from app.services import events, notify, roles
from app.services.events import EventError
from app.services.roles import RoleError
from tests.conftest import login, set_shortlist
from tests.test_weights import make_film, make_user

SOON = datetime.now(UTC) + timedelta(days=3)


async def test_event_without_film_needs_a_title(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    with pytest.raises(EventError, match="фильм или заголовок"):
        await events.create(session, starts_at=SOON, actor_id=boss.id)


async def test_secret_event_lives_outside_the_cycle(session):
    """Событие «ждите анонса»: время известно, фильм — нет."""
    boss = await make_user(session, "Админ")
    await session.commit()

    event = await events.create(
        session,
        starts_at=SOON,
        actor_id=boss.id,
        title="Секретный показ",
        note="ждите анонса",
    )

    assert event.is_manual is True
    assert event.film_id is None
    assert event.round_id is None
    assert event.note == "ждите анонса"

    slot = await session.get(Slot, event.slot_id)
    assert slot.round_id is None
    assert slot.starts_at == SOON


async def test_event_can_be_any_time_not_only_evenings(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    morning = datetime.now(UTC) + timedelta(days=2, hours=3)
    event = await events.create(
        session, starts_at=morning, actor_id=boss.id, title="Утренний показ"
    )
    slot = await session.get(Slot, event.slot_id)
    assert slot.starts_at == morning


async def test_two_events_cannot_share_hall_and_time(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    await events.create(session, starts_at=SOON, actor_id=boss.id, title="Первое")
    with pytest.raises(EventError, match="уже что-то назначено"):
        await events.create(session, starts_at=SOON, actor_id=boss.id, title="Второе")


async def test_cancelled_event_frees_the_time(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    first = await events.create(session, starts_at=SOON, actor_id=boss.id, title="Первое")
    first.status = ScreeningStatus.CANCELLED
    await session.commit()

    again = await events.create(session, starts_at=SOON, actor_id=boss.id, title="Второе")
    assert again.id != first.id


async def test_reveal_replaces_the_teaser_with_a_film(session):
    boss = await make_user(session, "Админ")
    film = await make_film(session, "Объявленный фильм")
    await session.commit()

    event = await events.create(
        session, starts_at=SOON, actor_id=boss.id, title="Секрет", note="ждите анонса"
    )
    revealed = await events.reveal(session, event.id, film.id, boss.id)

    assert revealed.film_id == film.id


async def test_event_can_be_moved_and_confirmations_reset(session):
    """Перенос — то же правило, что и у показов цикла (§7): вечер другой,
    значит и «приду» надо подтверждать заново."""
    boss = await make_user(session, "Админ")
    guest = await make_user(session, "Гость")
    await session.commit()

    event = await events.create(session, starts_at=SOON, actor_id=boss.id, title="Встреча")
    session.add(
        Confirmation(screening_id=event.id, user_id=guest.id, state=ConfirmationState.CONFIRMED)
    )
    await session.commit()

    later = SOON + timedelta(days=1)
    await events.update(session, event.id, boss.id, {"starts_at": later})

    slot = await session.get(Slot, event.slot_id)
    assert slot.starts_at == later
    left = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Confirmation)
        .where(Confirmation.screening_id == event.id)
    )
    assert left == 0
    # Гостя предупредили, а не переставили молча.
    kinds = (
        await session.execute(sa.select(Notification.kind).where(Notification.user_id == guest.id))
    ).scalars().all()
    assert kinds == ["screening_changed"]


async def test_editing_keeps_untouched_fields(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    event = await events.create(
        session, starts_at=SOON, actor_id=boss.id, title="Секрет", note="ждите анонса"
    )
    await events.update(session, event.id, boss.id, {"note": "начало в фойе"})

    assert event.title == "Секрет"
    assert event.note == "начало в фойе"
    slot = await session.get(Slot, event.slot_id)
    assert slot.starts_at == SOON


async def test_event_cannot_be_left_without_film_and_title(session):
    boss = await make_user(session, "Админ")
    film = await make_film(session, "Фильм")
    await session.commit()

    event = await events.create(session, starts_at=SOON, actor_id=boss.id, film_id=film.id)
    with pytest.raises(EventError, match="фильм или заголовок"):
        await events.update(session, event.id, boss.id, {"film_id": None})


async def test_event_cannot_move_onto_another(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    first = await events.create(session, starts_at=SOON, actor_id=boss.id, title="Первое")
    second = await events.create(
        session, starts_at=SOON + timedelta(days=1), actor_id=boss.id, title="Второе"
    )

    with pytest.raises(EventError, match="уже что-то назначено"):
        await events.update(session, second.id, boss.id, {"starts_at": SOON})
    # Само событие при этом осталось на своём месте.
    slot = await session.get(Slot, second.slot_id)
    assert slot.starts_at == SOON + timedelta(days=1)
    assert first.id != second.id


async def test_upcoming_skips_the_past(session):
    boss = await make_user(session, "Админ")
    await session.commit()

    future = await events.create(session, starts_at=SOON, actor_id=boss.id, title="Будущее")
    old = await events.create(
        session,
        starts_at=datetime.now(UTC) - timedelta(days=5),
        actor_id=boss.id,
        title="Прошедшее",
    )

    listed = [e.id for e in await events.upcoming(session)]
    assert future.id in listed
    assert old.id not in listed


async def test_upcoming_does_not_cut_off_far_future_events(session):
    """Анонс за полгода админ обязан видеть — иначе его не поправить и не снять."""
    boss = await make_user(session, "Админ")
    await session.commit()

    far = await events.create(
        session,
        starts_at=datetime.now(UTC) + timedelta(days=200),
        actor_id=boss.id,
        title="День рождения клуба",
    )

    assert far.id in [e.id for e in await events.upcoming(session)]
    # Горизонт остаётся доступен тем, кому нужны только ближайшие.
    assert far.id not in [e.id for e in await events.upcoming(session, within_days=60)]


async def test_manual_event_ignores_one_film_per_round_rule(session):
    """У ручных событий нет цикла, поэтому правило §6 к ним не относится."""
    boss = await make_user(session, "Админ")
    film = await make_film(session, "Один и тот же")
    await session.commit()

    first = await events.create(
        session, starts_at=SOON, actor_id=boss.id, film_id=film.id
    )
    second = await events.create(
        session, starts_at=SOON + timedelta(days=1), actor_id=boss.id, film_id=film.id
    )
    assert first.id != second.id

    total = await session.scalar(
        sa.select(sa.func.count()).select_from(Screening).where(Screening.is_manual.is_(True))
    )
    assert total == 2


# --- Роли -------------------------------------------------------------------


async def test_superadmin_can_appoint_admins(session):
    boss = await make_user(session, "Главный")
    boss.role = UserRole.SUPERADMIN
    target = await make_user(session, "Новый админ")
    await session.commit()

    updated = await roles.assign(session, boss, target.id, UserRole.ADMIN)
    assert updated.role == UserRole.ADMIN


async def test_admin_can_appoint_only_moderators(session):
    """§9: админ назначает модераторов, админов — только главный."""
    admin = await make_user(session, "Админ")
    admin.role = UserRole.ADMIN
    target = await make_user(session, "Кандидат")
    await session.commit()

    moderator = await roles.assign(session, admin, target.id, UserRole.MODERATOR)
    assert moderator.role == UserRole.MODERATOR

    with pytest.raises(RoleError, match="не можете выдавать"):
        await roles.assign(session, admin, target.id, UserRole.ADMIN)


async def test_moderator_cannot_assign_roles(session):
    moderator = await make_user(session, "Модератор")
    moderator.role = UserRole.MODERATOR
    target = await make_user(session, "Кандидат")
    await session.commit()

    with pytest.raises(RoleError, match="не можете выдавать"):
        await roles.assign(session, moderator, target.id, UserRole.MODERATOR)


async def test_cannot_demote_yourself(session):
    """Иначе клуб остался бы без главного админа, и вернуть роль было бы некому."""
    boss = await make_user(session, "Главный")
    boss.role = UserRole.SUPERADMIN
    await session.commit()

    with pytest.raises(RoleError, match="Свою роль"):
        await roles.assign(session, boss, boss.id, UserRole.USER)


async def test_superadmin_role_is_not_transferable_in_app(session):
    boss = await make_user(session, "Главный")
    boss.role = UserRole.SUPERADMIN
    other = await make_user(session, "Второй главный")
    other.role = UserRole.SUPERADMIN
    await session.commit()

    with pytest.raises(RoleError, match="настройках сервера"):
        await roles.assign(session, boss, other.id, UserRole.USER)


async def test_role_can_be_taken_away(session):
    boss = await make_user(session, "Главный")
    boss.role = UserRole.SUPERADMIN
    admin = await make_user(session, "Бывший админ")
    admin.role = UserRole.ADMIN
    await session.commit()

    updated = await roles.assign(session, boss, admin.id, UserRole.USER)
    assert updated.role == UserRole.USER


async def test_admin_cannot_touch_another_admin(session):
    """Иначе разжалование было бы гонкой: прав тот, кто нажал первым."""
    admin = await make_user(session, "Админ")
    admin.role = UserRole.ADMIN
    other = await make_user(session, "Другой админ")
    other.role = UserRole.ADMIN
    await session.commit()

    with pytest.raises(RoleError, match="равного"):
        await roles.assign(session, admin, other.id, UserRole.USER)


async def test_role_grant_notifies_the_person(session):
    """Человек должен узнать о роли, а не наткнуться на новую вкладку."""
    boss = await make_user(session, "Главный")
    boss.role = UserRole.SUPERADMIN
    target = await make_user(session, "Новый модератор")
    await session.commit()

    await roles.assign(session, boss, target.id, UserRole.MODERATOR)

    queued = (
        await session.execute(
            sa.select(Notification).where(Notification.user_id == target.id)
        )
    ).scalars().all()
    assert len(queued) == 1
    text = notify.render(queued[0].kind, None, "—", queued[0].payload)
    assert "модератор" in text

    # Снятие роли — тоже новость, но с другим текстом.
    await roles.assign(session, boss, target.id, UserRole.USER)
    demoted = (
        await session.execute(
            sa.select(Notification)
            .where(Notification.user_id == target.id)
            .order_by(Notification.id.desc())
        )
    ).scalars().first()
    assert "изменена" in notify.render(demoted.kind, None, "—", demoted.payload)


async def test_team_lists_only_people_with_roles(session):
    boss = await make_user(session, "Главный")
    boss.role = UserRole.SUPERADMIN
    await make_user(session, "Обычный участник")
    moderator = await make_user(session, "Модератор")
    moderator.role = UserRole.MODERATOR
    await session.commit()

    listed = {member.display_name for member in await roles.team(session)}
    assert listed == {"Главный", "Модератор"}


async def test_search_finds_by_name_and_username(session):
    user = await make_user(session, "Иван Петров")
    user.tg_username = "vanya"
    await session.commit()

    assert [u.id for u in await roles.search(session, "Петров")] == [user.id]
    assert [u.id for u in await roles.search(session, "vany")] == [user.id]
    assert await roles.search(session, "нетакого") == []


async def test_secret_event_visible_before_the_cycle_is_published(client, session):
    """Анонс не должен прятаться за этапом цикла: иначе его не увидит никто."""
    from datetime import date, time
    from zoneinfo import ZoneInfo

    from app.services import rounds as rounds_service

    boss_auth = await login(client, 777001, "Главный")
    boss_headers = {"Authorization": f"Bearer {boss_auth['token']}"}

    # Цикл в самом начале — показы ещё не опубликованы.
    week = date(2026, 9, 14)
    await rounds_service.open_round(session, week, boss_auth["user"]["id"])

    # Событие внутри той же недели, что и цикл, — оно должно быть видно сразу.
    moscow = ZoneInfo("Europe/Moscow")
    when = datetime.combine(date(2026, 9, 16), time(19, 0), tzinfo=moscow)
    created = await client.post(
        "/api/admin/events",
        json={"starts_at": when.isoformat(), "title": "Секретный показ", "note": "ждите анонса"},
        headers=boss_headers,
    )
    assert created.status_code == 201

    viewer = await login(client, 777099, "Обычный участник")
    schedule = (
        await client.get(
            f"/api/schedule?week={week}",
            headers={"Authorization": f"Bearer {viewer['token']}"},
        )
    ).json()

    titles = [item["film"]["title_ru"] for item in schedule["screenings"]]
    assert "Секретный показ" in titles
    assert schedule["screenings"][0]["note"] == "ждите анонса"
    assert schedule["screenings"][0]["is_manual"] is True


async def test_events_belong_to_their_week(client, session):
    """Листание по неделям: событие видно на своей неделе и не видно на соседней."""
    from datetime import date, time
    from zoneinfo import ZoneInfo

    boss = await login(client, 777001, "Главный")
    headers = {"Authorization": f"Bearer {boss['token']}"}

    moscow = ZoneInfo("Europe/Moscow")
    when = datetime.combine(date(2026, 9, 16), time(19, 0), tzinfo=moscow)
    await client.post(
        "/api/admin/events",
        json={"starts_at": when.isoformat(), "title": "Своё событие"},
        headers=headers,
    )

    on_week = (await client.get("/api/schedule?week=2026-09-14", headers=headers)).json()
    assert [s["film"]["title_ru"] for s in on_week["screenings"]] == ["Своё событие"]

    next_week = (await client.get("/api/schedule?week=2026-09-21", headers=headers)).json()
    assert next_week["screenings"] == []
    # Слева есть что показать — стрелка «назад» должна быть активна.
    assert next_week["has_prev"] is True


async def test_any_date_is_snapped_to_its_monday(client, session):
    """Неделя задаётся понедельником: середина недели должна вести туда же."""
    boss = await login(client, 777001, "Главный")
    headers = {"Authorization": f"Bearer {boss['token']}"}

    wednesday = (await client.get("/api/schedule?week=2026-09-16", headers=headers)).json()
    assert wednesday["week_start"] == "2026-09-14"


async def test_ordinary_user_still_cannot_see_unpublished_round(client, session):
    """Показы цикла до публикации остаются скрытыми."""
    from datetime import date

    from app.models import Film
    from app.services import rounds as rounds_service

    film = Film(title_ru="Не для чужих глаз")
    session.add(film)
    await session.commit()

    boss = await login(client, 777001, "Главный")
    boss_id = boss["user"]["id"]
    round_ = await rounds_service.open_round(session, date(2026, 9, 14), boss_id)
    await set_shortlist(session, round_, [film.id], boss_id)

    viewer = await login(client, 777098, "Обычный")
    schedule = (
        await client.get(
            "/api/schedule", headers={"Authorization": f"Bearer {viewer['token']}"}
        )
    ).json()

    assert schedule["screenings"] == []


async def test_confirm_works_for_manual_event(session):
    """У ручного события нет цикла — проверка его этапа не должна применяться."""
    from app.models.enums import ConfirmationState
    from app.services import schedule as sched

    boss = await make_user(session, "Админ")
    guest = await make_user(session, "Гость")
    await session.commit()

    event = await events.create(
        session, starts_at=SOON, actor_id=boss.id, title="Секретный показ", note="Ждите анонса"
    )

    result = await sched.confirm(session, event.id, guest.id)
    assert result.state == ConfirmationState.CONFIRMED
    assert result.confirmed == 1

    # И отменить приход тоже можно.
    cancelled = await sched.cancel(session, event.id, guest.id, late_cancel_hours=24)
    assert cancelled.state == ConfirmationState.CANCELLED
    assert cancelled.confirmed == 0


async def test_waitlist_works_for_manual_event(session):
    """Вместимость зала действует и на события вне цикла."""
    from app.models import Hall
    from app.models.enums import ConfirmationState
    from app.services import schedule as sched

    boss = await make_user(session, "Админ")
    await session.commit()
    event = await events.create(session, starts_at=SOON, actor_id=boss.id, title="Малый зал")

    hall = (await session.execute(sa.select(Hall))).scalars().first()
    hall.capacity = 1
    await session.commit()

    first = await make_user(session, "Первый")
    second = await make_user(session, "Второй")
    await session.commit()

    assert (await sched.confirm(session, event.id, first.id)).state == ConfirmationState.CONFIRMED
    queued = await sched.confirm(session, event.id, second.id)
    assert queued.state == ConfirmationState.WAITLIST
    assert queued.place_in_queue == 1


async def test_schedule_opens_on_the_current_week(client, session):
    """Открывать расписание на неделе активного цикла нельзя: тот готовится
    к следующей, и человек увидел бы пустой экран вместо сегодняшних показов."""
    from datetime import date, timedelta

    from app.services import rounds as rounds_service

    boss = await login(client, 777001, "Главный")
    headers = {"Authorization": f"Bearer {boss['token']}"}

    today = date.today()
    this_week = today - timedelta(days=today.weekday())
    next_week = this_week + timedelta(days=7)

    # Цикл готовится к следующей неделе — как и бывает в обычной работе.
    await rounds_service.open_round(session, next_week, boss["user"]["id"])

    opened = (await client.get("/api/schedule", headers=headers)).json()
    assert opened["week_start"] == this_week.isoformat()


async def test_voting_week_is_pointed_at_from_another_week(client, session):
    """Голосование — единственное, что требует действия; прятать его за
    листанием нельзя."""
    from datetime import date, timedelta

    from app.models.enums import RoundStage
    from app.services import rounds as rounds_service

    boss = await login(client, 777001, "Главный")
    headers = {"Authorization": f"Bearer {boss['token']}"}

    today = date.today()
    this_week = today - timedelta(days=today.weekday())
    next_week = this_week + timedelta(days=7)

    film = await make_film(session, "Фильм")
    await session.commit()
    round_ = await rounds_service.open_round(session, next_week, boss["user"]["id"])
    await set_shortlist(session, round_, [film.id], boss["user"]["id"])
    await rounds_service.publish_shortlist(session, round_, boss["user"]["id"])
    assert round_.stage == RoundStage.SLOT_VOTING

    here = (await client.get("/api/schedule", headers=headers)).json()
    assert here["week_start"] == this_week.isoformat()
    assert here["voting_week"] == next_week.isoformat()

    # На самой неделе голосования подсказка не нужна — человек уже там.
    there = (await client.get(f"/api/schedule?week={next_week}", headers=headers)).json()
    assert there["voting_week"] is None


async def test_dead_current_week_is_skipped(client, session):
    """В субботу вечером показывать доживающую пустую неделю бессмысленно —
    открываем ближайшую, где что-то есть."""
    from datetime import UTC, datetime, timedelta

    boss = await login(client, 777001, "Главный")
    headers = {"Authorization": f"Bearer {boss['token']}"}

    # Единственное событие — на следующей неделе.
    when = datetime.now(UTC) + timedelta(days=9)
    await client.post(
        "/api/admin/events",
        json={"starts_at": when.isoformat(), "title": "Через полторы недели"},
        headers=headers,
    )

    opened = (await client.get("/api/schedule", headers=headers)).json()
    titles = [s["film"]["title_ru"] for s in opened["screenings"]]
    assert titles == ["Через полторы недели"]


async def test_current_week_kept_while_something_is_left(client, session):
    """Пока на этой неделе есть что впереди — остаёмся на ней."""
    from datetime import UTC, datetime, timedelta

    boss = await login(client, 777001, "Главный")
    headers = {"Authorization": f"Bearer {boss['token']}"}

    soon = datetime.now(UTC) + timedelta(hours=6)
    later = datetime.now(UTC) + timedelta(days=9)
    for when, title in ((soon, "Сегодня"), (later, "Потом")):
        await client.post(
            "/api/admin/events",
            json={"starts_at": when.isoformat(), "title": title},
            headers=headers,
        )

    opened = (await client.get("/api/schedule", headers=headers)).json()
    assert "Сегодня" in [s["film"]["title_ru"] for s in opened["screenings"]]
