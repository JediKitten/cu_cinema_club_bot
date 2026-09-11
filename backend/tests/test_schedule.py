"""Этап 3: расстановка показов, публикация, подтверждения (§7)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Confirmation, Hall, Notification, Screening, Slot
from app.models.enums import ConfirmationState, NotificationKind, RoundStage, ScreeningStatus
from app.services import schedule as sched
from app.services import voting
from app.services.schedule import ScheduleError
from tests.conftest import TEST_DB, _url
from tests.test_voting import prepared_round
from tests.test_weights import make_user


async def voted_round(session, capacity: int = 40):
    """Цикл с проголосовавшими людьми — от него пляшет вся расстановка."""
    round_, films, slots, boss = await prepared_round(session)

    hall = (await session.execute(sa.select(Hall))).scalars().first()
    hall.capacity = capacity
    await session.commit()

    voters = [await make_user(session, f"Зритель {i}") for i in range(3)]
    await session.commit()
    for voter in voters:
        await voting.set_votes(session, round_, voter.id, [films[0].id])
        await voting.set_availability(session, round_, voter.id, [slots[0].id])

    return round_, films, slots, boss, voters


async def test_assign_records_expected_attendance(session):
    """Ожидаемая явка — ячейка матрицы этапа 2, сохранённая снимком."""
    round_, films, slots, boss, _ = await voted_round(session)

    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    assert screening.expected_attendance == 3
    assert round_.stage == RoundStage.SCHEDULE_REVIEW


async def test_one_screening_per_evening(session):
    round_, films, slots, boss, _ = await voted_round(session)
    await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)

    with pytest.raises(ScheduleError, match="уже назначен"):
        await sched.assign(session, round_, films[1].id, slots[0].id, boss.id)


async def test_film_only_once_per_round(session):
    round_, films, slots, boss, _ = await voted_round(session)
    await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)

    with pytest.raises(ScheduleError, match="уже стоит"):
        await sched.assign(session, round_, films[0].id, slots[1].id, boss.id)


async def test_blocked_evening_rejected(session):
    round_, films, slots, boss, _ = await voted_round(session)
    from app.services import rounds as rounds_service

    await rounds_service.set_slot_blocked(session, slots[0].id, True, "пары", boss.id)

    with pytest.raises(ScheduleError, match="закрыт"):
        await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)


async def test_publish_invites_only_those_who_voted(session):
    """Приглашение уходит тем, кто голосовал за назначенный фильм (§7)."""
    round_, films, slots, boss, voters = await voted_round(session)
    outsider = await make_user(session, "Не голосовал")
    await session.commit()

    await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    assert round_.stage == RoundStage.PUBLISHED
    invited = set(
        (
            await session.execute(
                sa.select(Notification.user_id).where(
                    Notification.kind == NotificationKind.SCHEDULE_PUBLISHED
                )
            )
        )
        .scalars()
        .all()
    )
    assert invited == {v.id for v in voters}
    assert outsider.id not in invited


async def test_publish_is_idempotent_in_notifications(session):
    """Повторная публикация не должна слать второе приглашение."""
    round_, films, slots, boss, voters = await voted_round(session)
    await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    before = await session.scalar(sa.select(sa.func.count()).select_from(Notification))
    with pytest.raises(ScheduleError, match="уже опубликовано"):
        await sched.publish_schedule(session, round_, boss.id)
    after = await session.scalar(sa.select(sa.func.count()).select_from(Notification))
    assert before == after


async def test_publish_requires_screenings(session):
    round_, _, _, boss, _ = await voted_round(session)
    with pytest.raises(ScheduleError, match="расставьте"):
        await sched.publish_schedule(session, round_, boss.id)


async def test_confirm_fills_hall_then_waitlist(session):
    """Подтверждения ограничены вместимостью, дальше — лист ожидания (§7)."""
    round_, films, slots, boss, voters = await voted_round(session, capacity=2)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    first = await sched.confirm(session, screening.id, voters[0].id)
    second = await sched.confirm(session, screening.id, voters[1].id)
    third = await sched.confirm(session, screening.id, voters[2].id)

    assert first.state == ConfirmationState.CONFIRMED
    assert second.state == ConfirmationState.CONFIRMED
    assert third.state == ConfirmationState.WAITLIST
    assert third.place_in_queue == 1
    assert third.confirmed == 2


async def test_cancel_promotes_first_in_queue(session):
    round_, films, slots, boss, voters = await voted_round(session, capacity=1)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    await sched.confirm(session, screening.id, voters[0].id)
    await sched.confirm(session, screening.id, voters[1].id)  # в очередь

    await sched.cancel(session, screening.id, voters[0].id, late_cancel_hours=24)

    promoted = (
        await session.execute(
            sa.select(Confirmation).where(
                Confirmation.screening_id == screening.id,
                Confirmation.user_id == voters[1].id,
            )
        )
    ).scalar_one()
    assert promoted.state == ConfirmationState.CONFIRMED

    told = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Notification)
        .where(
            Notification.kind == NotificationKind.WAITLIST_PROMOTED,
            Notification.user_id == voters[1].id,
        )
    )
    assert told == 1


async def test_late_cancel_is_recorded(session):
    """Санкций нет, но поздняя отмена попадает в статистику (§7)."""
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    # Сдвигаем сеанс на через два часа — отмена оказывается поздней.
    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) + timedelta(hours=2)
    await session.commit()

    await sched.cancel(session, screening.id, voters[0].id, late_cancel_hours=24)

    confirmation = (
        await session.execute(
            sa.select(Confirmation).where(
                Confirmation.screening_id == screening.id,
                Confirmation.user_id == voters[0].id,
            )
        )
    ).scalar_one()
    assert confirmation.state == ConfirmationState.CANCELLED
    assert confirmation.was_late_cancel is True


async def test_early_cancel_is_not_late(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) + timedelta(days=3)
    await session.commit()

    await sched.cancel(session, screening.id, voters[0].id, late_cancel_hours=24)
    confirmation = (
        await session.execute(
            sa.select(Confirmation).where(Confirmation.user_id == voters[0].id)
        )
    ).scalar_one()
    assert confirmation.was_late_cancel is False


async def test_confirm_before_publication_refused(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)

    with pytest.raises(ScheduleError, match="не опубликовано"):
        await sched.confirm(session, screening.id, voters[0].id)


async def test_moving_to_another_evening_resets_confirmations(session):
    """§7: доступность привязана к окну, поэтому перенос по времени сбрасывает
    подтверждения — молча переносить людей нельзя."""
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    await sched.move_screening(session, screening.id, slots[2].id, boss.id)

    left = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Confirmation)
        .where(Confirmation.screening_id == screening.id)
    )
    assert left == 0

    told = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Notification)
        .where(Notification.kind == NotificationKind.SCREENING_CHANGED)
    )
    assert told >= 1


async def test_cancel_screening_requires_comment(session):
    round_, films, slots, boss, _ = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    with pytest.raises(ScheduleError, match="комментарий"):
        await sched.cancel_screening(session, screening.id, "   ", boss.id)


async def test_cancel_screening_notifies_confirmed(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    await sched.cancel_screening(session, screening.id, "прорвало трубу", boss.id)

    updated = await session.get(Screening, screening.id)
    assert updated.status == ScreeningStatus.CANCELLED
    assert updated.cancel_reason == "прорвало трубу"

    payloads = (
        (
            await session.execute(
                sa.select(Notification.payload).where(
                    Notification.kind == NotificationKind.SCREENING_CANCELLED
                )
            )
        )
        .scalars()
        .all()
    )
    assert payloads and payloads[0]["reason"] == "прорвало трубу"


async def test_cancelled_screening_frees_the_evening(session):
    """Отменённый показ не должен держать вечер занятым."""
    round_, films, slots, boss, _ = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.cancel_screening(session, screening.id, "не смогли", boss.id)

    round_.stage = RoundStage.SCHEDULE_REVIEW
    await session.commit()
    again = await sched.assign(session, round_, films[1].id, slots[0].id, boss.id)
    assert again.id != screening.id


async def test_last_seat_does_not_go_to_two_people_at_once(session):
    """Два «Приду» на последнее место в один момент — пройти должен один.

    Места считаются чтением, а занимаются записью, и между этими шагами
    вклинивается чужой запрос: без блокировки строки показа оба видят
    свободное место, и в зале оказывается на человека больше, чем стульев.
    Поэтому тест идёт двумя настоящими соединениями, а не одной сессией.
    """
    round_, films, slots, boss, voters = await voted_round(session, capacity=1)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await session.commit()

    engine = create_async_engine(_url(TEST_DB))
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as one, maker() as two:
            results = await asyncio.wait_for(
                asyncio.gather(
                    sched.confirm(one, screening.id, voters[0].id),
                    sched.confirm(two, screening.id, voters[1].id),
                ),
                timeout=15,
            )
    finally:
        await engine.dispose()

    assert sorted(result.state for result in results) == [
        ConfirmationState.CONFIRMED,
        ConfirmationState.WAITLIST,
    ]


async def test_queue_is_not_overtaken_by_pressing_again(session):
    """Стоящий в очереди не обгоняет её повторным нажатием «Приду».

    Место, освободившееся после отмены, принадлежит первому в очереди, а не
    тому, кто чаще открывает приложение.
    """
    round_, films, slots, boss, voters = await voted_round(session, capacity=1)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    await sched.confirm(session, screening.id, voters[0].id)
    await sched.confirm(session, screening.id, voters[1].id)  # первый в очереди
    await sched.confirm(session, screening.id, voters[2].id)  # второй в очереди

    # Место освободилось, но очередь двигает только promote_from_waitlist.
    confirmation = (
        await session.execute(
            sa.select(Confirmation).where(
                Confirmation.screening_id == screening.id,
                Confirmation.user_id == voters[0].id,
            )
        )
    ).scalar_one()
    confirmation.state = ConfirmationState.CANCELLED
    await session.commit()

    impatient = await sched.confirm(session, screening.id, voters[2].id)
    assert impatient.state == ConfirmationState.WAITLIST
    assert impatient.place_in_queue == 2


async def test_returning_after_cancel_goes_to_the_end_of_the_queue(session):
    """Отменился и вернулся — встаёт за теми, кто записался, пока его не было."""
    round_, films, slots, boss, voters = await voted_round(session, capacity=1)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    await sched.confirm(session, screening.id, voters[0].id)  # занял место
    await sched.confirm(session, screening.id, voters[1].id)  # в очередь
    # Уходит первый: очередь двигается, место занимает voters[1].
    await sched.cancel(session, screening.id, voters[0].id, late_cancel_hours=24)
    await sched.confirm(session, screening.id, voters[2].id)  # встал в очередь

    returned = await sched.confirm(session, screening.id, voters[0].id)

    assert returned.state == ConfirmationState.WAITLIST
    assert returned.place_in_queue == 2


async def test_repeat_confirm_is_idempotent(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    await sched.confirm(session, screening.id, voters[0].id)
    result = await sched.confirm(session, screening.id, voters[0].id)

    assert result.state == ConfirmationState.CONFIRMED
    assert result.confirmed == 1
