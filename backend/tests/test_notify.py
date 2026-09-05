"""Уведомления и фоновые задачи (§7, §17).

Главное требование спека к фоновым задачам — идемпотентность: повторный
запуск не должен приводить к дублю уведомлений.
"""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.models import Confirmation, Notification, Slot, User
from app.models.enums import NotificationKind, UserRole
from app.services import notify, reminders
from app.services import schedule as sched
from tests.test_schedule import voted_round
from tests.test_weights import make_user


class FakeBot:
    """Бот, который только запоминает отправленное."""

    def __init__(self, fail_for: set[int] | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail_for = fail_for or set()

    async def send_message(self, chat_id: int, text: str) -> None:
        if chat_id in self.fail_for:
            raise RuntimeError("bot was blocked by the user")
        self.sent.append((chat_id, text))


def moscow(value) -> str:
    return value.strftime("%d.%m %H:%M")


async def test_queue_skips_duplicates(session):
    user = await make_user(session, "Адресат")
    await session.commit()

    first = await notify.queue(session, user.id, NotificationKind.REMINDER_24H, "k1", {})
    second = await notify.queue(session, user.id, NotificationKind.REMINDER_24H, "k1", {})
    await session.commit()

    assert first is True
    assert second is False
    assert await session.scalar(sa.select(sa.func.count()).select_from(Notification)) == 1


async def test_delivery_marks_sent_and_does_not_resend(session):
    user = await make_user(session, "Адресат")
    await session.commit()
    await notify.queue(session, user.id, NotificationKind.REMINDER_2H, "k", {})
    await session.commit()

    bot = FakeBot()
    assert await notify.deliver(session, bot, moscow) == 1
    assert len(bot.sent) == 1

    # Второй проход не должен отправить то же самое ещё раз.
    assert await notify.deliver(session, bot, moscow) == 0
    assert len(bot.sent) == 1


async def test_one_bad_recipient_does_not_block_the_queue(session):
    """Заблокировавший бота не должен останавливать рассылку остальным."""
    blocked = await make_user(session, "Заблокировал")
    fine = await make_user(session, "Обычный")
    await session.commit()

    await notify.queue(session, blocked.id, NotificationKind.REMINDER_2H, "a", {})
    await notify.queue(session, fine.id, NotificationKind.REMINDER_2H, "b", {})
    await session.commit()

    bot = FakeBot(fail_for={blocked.tg_id})
    sent = await notify.deliver(session, bot, moscow)

    assert sent == 1
    assert bot.sent[0][0] == fine.tg_id

    failed = (
        await session.execute(
            sa.select(Notification).where(Notification.user_id == blocked.id)
        )
    ).scalar_one()
    assert failed.sent_at is None
    assert "blocked" in failed.failed_reason


async def test_user_without_telegram_is_marked_not_retried(session):
    user = User(display_name="Без телеграма", tg_id=None)
    session.add(user)
    await session.commit()
    await notify.queue(session, user.id, NotificationKind.REMINDER_2H, "x", {})
    await session.commit()

    bot = FakeBot()
    assert await notify.deliver(session, bot, moscow) == 0

    row = (await session.execute(sa.select(Notification))).scalar_one()
    assert row.failed_reason == "нет привязки Telegram"


async def test_reminder_is_sent_once_however_often_the_task_runs(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    # Сеанс завтра — попадает в окно напоминания за 24 часа.
    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) + timedelta(hours=23)
    await session.commit()

    assert await reminders.send_reminders(session, 24) == 1
    assert await reminders.send_reminders(session, 24) == 0

    count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Notification)
        .where(Notification.kind == NotificationKind.REMINDER_24H)
    )
    assert count == 1

    confirmation = (
        await session.execute(
            sa.select(Confirmation).where(Confirmation.user_id == voters[0].id)
        )
    ).scalar_one()
    assert confirmation.reminded_24h_at is not None


async def test_cancelled_participant_gets_no_reminder(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)
    await sched.cancel(session, screening.id, voters[0].id, late_cancel_hours=24)

    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) + timedelta(hours=23)
    await session.commit()

    assert await reminders.send_reminders(session, 24) == 0


async def test_low_attendance_warns_admins_once(session):
    """Предупреждение о недоборе — админам и ровно один раз (§7)."""
    round_, films, slots, boss, voters = await voted_round(session)
    boss.role = UserRole.SUPERADMIN
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)  # один при кворуме 5

    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) + timedelta(hours=20)
    await session.commit()

    assert await reminders.warn_low_attendance(session) == 1
    assert await reminders.warn_low_attendance(session) == 0

    warning = (
        await session.execute(
            sa.select(Notification).where(
                Notification.kind == NotificationKind.ADMIN_LOW_ATTENDANCE
            )
        )
    ).scalar_one()
    assert warning.user_id == boss.id
    assert warning.payload["confirmed"] == 1


async def test_no_warning_when_quorum_reached(session):
    round_, films, slots, boss, voters = await voted_round(session)
    boss.role = UserRole.SUPERADMIN
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    # Кворум по умолчанию 5 — набираем его.
    extra = [await make_user(session, f"Гость {i}") for i in range(5)]
    await session.commit()
    for user in extra:
        await sched.confirm(session, screening.id, user.id)

    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) + timedelta(hours=20)
    await session.commit()

    assert await reminders.warn_low_attendance(session) == 0


async def test_messages_mention_the_film_and_time(session):
    """Текст без названия фильма бесполезен: у человека может быть несколько сеансов."""
    round_, films, slots, boss, _voters = await voted_round(session)
    await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)

    bot = FakeBot()
    await notify.deliver(session, bot, moscow)

    assert bot.sent
    text = bot.sent[0][1]
    assert films[0].title_ru in text
    assert "Расписание готово" in text


async def test_cancellation_message_carries_the_reason(session):
    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    bot = FakeBot()
    await notify.deliver(session, bot, moscow)  # разгребаем приглашения
    bot.sent.clear()

    await sched.cancel_screening(session, screening.id, "прорвало трубу", boss.id)
    await notify.deliver(session, bot, moscow)

    assert any("прорвало трубу" in text for _, text in bot.sent)


async def test_run_all_is_safe_to_repeat(session):
    round_, films, slots, boss, voters = await voted_round(session)
    boss.role = UserRole.SUPERADMIN
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)

    slot = await session.get(Slot, slots[0].id)
    slot.starts_at = datetime.now(UTC) + timedelta(hours=23)
    await session.commit()

    first = await reminders.run_all(session)
    second = await reminders.run_all(session)

    assert sum(first.values()) > 0
    assert sum(second.values()) == 0
