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

    def __init__(self, fail_for: set[int] | None = None, error: Exception | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self.markups: list[object] = []
        self.fail_for = fail_for or set()
        # По умолчанию — отказ навсегда: человек заблокировал бота.
        self.error = error or RuntimeError("bot was blocked by the user")

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:
        if chat_id in self.fail_for:
            raise self.error
        self.sent.append((chat_id, text))
        self.markups.append(reply_markup)


class TelegramRetryAfter(Exception):
    """Ровно то, чем aiogram отвечает на 429: с числом секунд внутри."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Flood control exceeded. Retry in {retry_after} seconds")
        self.retry_after = retry_after


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


async def test_network_blip_postpones_instead_of_losing_the_message(session):
    """Временная ошибка не хоронит уведомление.

    Приглашение на показ уходит один раз: если сеть моргнула в этот момент,
    человек не узнает о сеансе никогда. Поэтому сетевая ошибка откладывает
    следующую попытку, а не выводит запись из очереди.
    """
    user = await make_user(session, "Адресат")
    await session.commit()
    await notify.queue(session, user.id, NotificationKind.SCHEDULE_PUBLISHED, "k", {})
    await session.commit()

    flaky = FakeBot(fail_for={user.tg_id}, error=TimeoutError("сеть моргнула"))
    assert await notify.deliver(session, flaky, moscow) == 0

    record = (await session.execute(sa.select(Notification))).scalar_one()
    await session.refresh(record)
    assert record.failed_reason is None
    assert record.attempts == 1
    assert record.next_attempt_at is not None

    # До назначенного времени запись в работу не берут — иначе очередь крутила
    # бы одно и то же сообщение каждые пять секунд.
    assert await notify.deliver(session, FakeBot(), moscow) == 0

    record.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()

    working = FakeBot()
    assert await notify.deliver(session, working, moscow) == 1
    assert working.sent[0][0] == user.tg_id


async def test_retries_run_out_and_the_message_is_given_up(session):
    """Попытки не бесконечны: Telegram, недоступный сутки, не держит очередь вечно."""
    user = await make_user(session, "Адресат")
    await session.commit()
    await notify.queue(session, user.id, NotificationKind.REMINDER_2H, "k", {})
    await session.commit()

    flaky = FakeBot(fail_for={user.tg_id}, error=TimeoutError("сеть лежит"))
    record = (await session.execute(sa.select(Notification))).scalar_one()

    for _ in range(notify.MAX_ATTEMPTS):
        record.next_attempt_at = None
        await session.commit()
        assert await notify.deliver(session, flaky, moscow) == 0

    await session.refresh(record)
    assert record.attempts == notify.MAX_ATTEMPTS
    assert "TimeoutError" in record.failed_reason


async def test_flood_control_waits_exactly_as_long_as_telegram_asked(session):
    """На 429 Telegram сам называет паузу — она точнее нашей лесенки."""
    user = await make_user(session, "Адресат")
    await session.commit()
    await notify.queue(session, user.id, NotificationKind.ADMIN_BROADCAST, "k", {"text": "тест"})
    await session.commit()

    flooded = FakeBot(fail_for={user.tg_id}, error=TelegramRetryAfter(retry_after=42))
    assert await notify.deliver(session, flooded, moscow) == 0

    record = (await session.execute(sa.select(Notification))).scalar_one()
    await session.refresh(record)
    waiting = record.next_attempt_at - datetime.now(UTC)
    assert timedelta(seconds=30) < waiting <= timedelta(seconds=42)


async def test_sent_message_survives_a_failure_later_in_the_batch(session):
    """Отправленное фиксируется сразу, а не в конце пачки.

    Иначе падение процесса между отправкой и коммитом рассылало бы всю пачку
    повторно: дедупликация защищает от второй записи в очереди, но не от
    второго сообщения человеку.
    """
    first = await make_user(session, "Первый")
    second = await make_user(session, "Второй")
    await session.commit()
    await notify.queue(session, first.id, NotificationKind.REMINDER_2H, "a", {})
    await notify.queue(session, second.id, NotificationKind.REMINDER_2H, "b", {})
    await session.commit()

    bot = FakeBot(fail_for={second.tg_id}, error=TimeoutError("сеть моргнула"))
    assert await notify.deliver(session, bot, moscow) == 1

    # Откат посреди работы не должен отменить уже отправленное.
    await session.rollback()
    delivered = (
        await session.execute(sa.select(Notification).where(Notification.user_id == first.id))
    ).scalar_one()
    assert delivered.sent_at is not None


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

    # В очереди к этому моменту лежит и объявление о старте голосования —
    # ищем именно приглашение на показ.
    text = next(body for _, body in bot.sent if "Расписание готово" in body)
    assert films[0].title_ru in text


async def test_opening_the_vote_is_announced_to_everyone(session):
    """Начало голосования не должно проходить молча.

    При включённом автопилоте этап 2 открывается сам, и раньше человек узнавал
    об этом, только если случайно открывал приложение в эти три дня.
    """
    from datetime import date

    from app.services import rounds as rounds_service
    from tests.conftest import set_shortlist
    from tests.test_rounds import admin
    from tests.test_weights import make_film

    boss = await admin(session)
    club = [await make_user(session, f"Участник {i}") for i in range(3)]
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    films = [await make_film(session, f"Фильм {i}") for i in range(3)]
    await session.commit()

    await set_shortlist(session, round_, [film.id for film in films], boss.id)
    await rounds_service.publish_shortlist(session, round_, boss.id)

    announced = (
        (
            await session.execute(
                sa.select(Notification).where(
                    Notification.kind == NotificationKind.SHORTLIST_PUBLISHED
                )
            )
        )
        .scalars()
        .all()
    )

    assert {item.user_id for item in announced} >= {member.id for member in club}
    assert films[0].title_ru in announced[0].payload["films"]

    bot = FakeBot()
    await notify.deliver(session, bot, moscow)
    text = next(body for _, body in bot.sent if "Голосование открыто" in body)
    assert films[0].title_ru in text


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


async def test_feedback_reminder_once_for_those_who_came(session):
    """Пришёл, не оценил — напоминаем один раз (§8)."""
    from datetime import UTC, datetime, timedelta

    import sqlalchemy as sa

    from app.models import Attendance
    from app.services import attendance as att

    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)
    await att.mark_manually(session, screening.id, voters[0].id, boss.id)

    # Ещё свежо — напоминать рано.
    assert await reminders.remind_about_feedback(session) == 0

    await session.execute(
        sa.update(Attendance).values(marked_at=datetime.now(UTC) - timedelta(hours=30))
    )
    await session.commit()

    assert await reminders.remind_about_feedback(session) == 1
    assert await reminders.remind_about_feedback(session) == 0


async def test_no_feedback_reminder_after_rating(session):
    from datetime import UTC, datetime, timedelta

    import sqlalchemy as sa

    from app.models import Attendance
    from app.services import attendance as att

    round_, films, slots, boss, voters = await voted_round(session)
    screening = await sched.assign(session, round_, films[0].id, slots[0].id, boss.id)
    await sched.publish_schedule(session, round_, boss.id)
    await sched.confirm(session, screening.id, voters[0].id)
    await att.mark_manually(session, screening.id, voters[0].id, boss.id)
    await att.save_feedback(session, screening.id, voters[0].id, 8, None, None)

    await session.execute(
        sa.update(Attendance).values(marked_at=datetime.now(UTC) - timedelta(hours=30))
    )
    await session.commit()

    assert await reminders.remind_about_feedback(session) == 0
