"""Цикл: слоты, шорт-лист, порядок этапов (§2, §3, §5, §10)."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa

from app.models import Round, ShortlistItem, Slot, User
from app.models.enums import InterestKind, RoundStage, UserRole
from app.services import rounds as rounds_service
from app.services.rounds import RoundError, next_week_start, week_start_for
from app.services.settings import SettingsService
from tests.test_weights import add_interest, make_film, make_user


async def admin(session) -> User:
    user = await make_user(session, "Админ")
    user.role = UserRole.SUPERADMIN
    await session.flush()
    return user


def test_week_start_is_monday():
    # Среда 2026-09-02 → понедельник 2026-08-31.
    assert week_start_for(date(2026, 9, 2)) == date(2026, 8, 31)
    assert week_start_for(date(2026, 8, 31)) == date(2026, 8, 31)
    assert next_week_start(date(2026, 9, 2)) == date(2026, 9, 7)
    assert next_week_start(date(2026, 9, 2)).weekday() == 0


async def test_open_round_creates_seven_evenings(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)

    slots = (
        await session.execute(
            sa.select(Slot).where(Slot.round_id == round_.id).order_by(Slot.starts_at)
        )
    ).scalars().all()
    assert len(slots) == 7
    assert all(not slot.blocked for slot in slots)

    # Время задаётся в зоне вуза, хранится в UTC. Проверяем, что 19:00 местного
    # действительно остались 19:00 местного, а не превратились в 19:00 UTC.
    tz = ZoneInfo(str(await SettingsService(session).get("display_timezone")))
    local = [slot.starts_at.astimezone(tz) for slot in slots]
    assert {moment.hour for moment in local} == {19}
    assert [moment.date() for moment in local] == [
        date(2026, 9, 7) + timedelta(days=offset) for offset in range(7)
    ]


async def test_open_round_is_idempotent(session):
    boss = await admin(session)
    first = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    second = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    assert first.id == second.id

    total = await session.scalar(sa.select(sa.func.count()).select_from(Slot))
    assert total == 7  # второй запуск не наплодил дублей


async def test_round_must_start_on_monday(session):
    boss = await admin(session)
    with pytest.raises(RoundError, match="понедельника"):
        await rounds_service.open_round(session, date(2026, 9, 8), boss.id)


async def test_shortlist_replaces_previous_selection(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    films = [await make_film(session, f"Фильм {i}") for i in range(4)]
    await session.commit()

    await rounds_service.set_shortlist(session, round_, [films[0].id, films[1].id], boss.id)
    await rounds_service.set_shortlist(session, round_, [films[2].id, films[3].id], boss.id)

    items = (
        await session.execute(
            sa.select(ShortlistItem)
            .where(ShortlistItem.round_id == round_.id)
            .order_by(ShortlistItem.position)
        )
    ).scalars().all()
    assert [item.film_id for item in items] == [films[2].id, films[3].id]
    assert [item.position for item in items] == [0, 1]
    assert round_.stage == RoundStage.SHORTLIST_REVIEW


async def test_shortlist_rejects_duplicates(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    film = await make_film(session, "Дубль")
    await session.commit()

    with pytest.raises(RoundError, match="повторяются"):
        await rounds_service.set_shortlist(session, round_, [film.id, film.id], boss.id)


async def test_publish_requires_shortlist(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)

    with pytest.raises(RoundError, match="соберите шорт-лист"):
        await rounds_service.publish_shortlist(session, round_, boss.id)


async def test_publish_opens_voting_and_locks_shortlist(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    film = await make_film(session, "Сталкер")
    await session.commit()
    await rounds_service.set_shortlist(session, round_, [film.id], boss.id)

    await rounds_service.publish_shortlist(session, round_, boss.id)
    assert round_.stage == RoundStage.SLOT_VOTING
    assert round_.shortlist_locked_at is not None

    # После публикации список менять нельзя: это меняло бы условия голосования.
    with pytest.raises(RoundError, match="опубликован"):
        await rounds_service.set_shortlist(session, round_, [film.id], boss.id)


async def test_publish_refused_when_every_evening_blocked(session):
    """Если все вечера заблокированы, этап 2 не запускается (§3)."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    film = await make_film(session, "Солярис")
    await session.commit()
    await rounds_service.set_shortlist(session, round_, [film.id], boss.id)

    slots = (
        await session.execute(sa.select(Slot).where(Slot.round_id == round_.id))
    ).scalars().all()
    for slot in slots:
        await rounds_service.set_slot_blocked(session, slot.id, True, "сессия", boss.id)

    with pytest.raises(RoundError, match="заблокированы"):
        await rounds_service.publish_shortlist(session, round_, boss.id)


async def test_autopilot_marks_low_activity(session):
    """Прошедших порог меньше размера шорт-листа — цикл помечается (§5)."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)

    voter = await make_user(session, "Единственный")
    film = await make_film(session, "Одинокий фильм")
    await add_interest(session, voter, film, InterestKind.SOON, 0)
    await session.commit()

    # Подсказка считается всегда, но флаг не поднимает: на свежем цикле отметок
    # ещё нет, и «низкая активность» была бы ложной тревогой.
    hint = await rounds_service.autopilot_shortlist(session, round_)
    assert hint == [film.id]
    assert round_.low_activity is False

    # А вот когда автопилот действительно решает — флаг уместен.
    decided = await rounds_service.autopilot_shortlist(session, round_, deciding=True)
    assert decided == [film.id]
    assert round_.low_activity is True


async def test_active_round_ignores_closed(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    assert (await rounds_service.active_round(session)).id == round_.id

    round_.stage = RoundStage.CLOSED
    await session.commit()
    assert await rounds_service.active_round(session) is None


async def test_hall_capacity_follows_settings(session):
    boss = await admin(session)
    await rounds_service.open_round(session, date(2026, 9, 7), boss.id)

    await SettingsService(session).set_many({"hall_capacity": 55}, boss.id)
    await session.commit()

    hall = await rounds_service.ensure_hall(session)
    await session.commit()
    assert hall.capacity == 55


async def test_round_and_films_isolated_between_weeks(session):
    boss = await admin(session)
    first = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    second = await rounds_service.open_round(session, date(2026, 9, 14), boss.id)
    assert first.id != second.id

    total_slots = await session.scalar(sa.select(sa.func.count()).select_from(Slot))
    assert total_slots == 14

    rounds_count = await session.scalar(sa.select(sa.func.count()).select_from(Round))
    assert rounds_count == 2
