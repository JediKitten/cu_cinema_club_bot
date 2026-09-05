"""Ручные события и назначение ролей (§9, §10)."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Screening, Slot
from app.models.enums import ScreeningStatus, UserRole
from app.services import events, roles
from app.services.events import EventError
from app.services.roles import RoleError
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
