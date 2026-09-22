"""Эксплуатация: ночная копия базы, сторож фоновых циклов, заблокировавшие бота.

Всё это — про то, чтобы о поломке узнавали из сообщения, а не по симптомам.
"""

import asyncio
import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from app.bot import loops
from app.bot.__main__ import build_dispatcher
from app.models import Notification, User
from app.models.enums import NotificationKind
from app.services import backup, broadcast, notify
from tests.test_notify import FakeBot, moscow
from tests.test_weights import make_user

MSK = ZoneInfo("Europe/Moscow")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=MSK)


# --- Когда снимать копию ------------------------------------------------------


def test_first_run_takes_a_copy_right_away(tmp_path: Path):
    """На чистом сервере ждать ночи незачем: копии нет ни одной."""
    assert backup.is_due(tmp_path, at(22, 15))
    assert backup.is_due(tmp_path / "missing", at(22, 15))


def test_one_copy_a_day_after_four_am(tmp_path: Path):
    (tmp_path / backup.filename(at(22, 4, 1))).write_bytes(b"x")

    assert not backup.is_due(tmp_path, at(22, 23))
    # Ночью, до четырёх, вчерашняя копия ещё считается свежей.
    assert not backup.is_due(tmp_path, at(23, 3, 59))
    assert backup.is_due(tmp_path, at(23, 4))


def test_copy_time_is_read_in_the_club_timezone(tmp_path: Path):
    """В контейнере системный пояс — UTC. Прочти имя в нём, и копия от 05:00
    по Москве выглядела бы снятой в 02:00 — до срока, — и снималась бы заново
    каждые десять минут до семи утра."""
    (tmp_path / backup.filename(at(22, 5))).write_bytes(b"x")
    assert not backup.is_due(tmp_path, at(22, 6))


def test_foreign_files_are_not_mistaken_for_copies(tmp_path: Path):
    (tmp_path / "cinema-20260922-0401-before-csat.sql.gz.part").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    assert backup.copies(tmp_path) == []
    assert backup.is_due(tmp_path, at(22, 12))


def test_rotation_keeps_the_newest(tmp_path: Path):
    for day in range(1, 21):
        (tmp_path / backup.filename(at(day, 4))).write_bytes(b"x")

    removed = backup.rotate(tmp_path, keep=14)

    assert len(removed) == 6
    left = backup.copies(tmp_path)
    assert len(left) == 14
    assert left[0].name == backup.filename(at(7, 4))
    assert left[-1].name == backup.filename(at(20, 4))


def test_save_never_leaves_a_half_written_copy(tmp_path: Path):
    path = backup.save(tmp_path / "new", "cinema-20260922-0400.sql.gz", b"data")
    assert path.read_bytes() == b"data"
    assert [p.name for p in path.parent.iterdir()] == [path.name]


# --- Снятие и отправка --------------------------------------------------------


class DocumentBot(FakeBot):
    def __init__(self) -> None:
        super().__init__()
        self.documents: list[tuple[int, str, bytes]] = []

    async def send_message(self, chat_id, text, reply_markup=None, **_) -> None:
        await super().send_message(chat_id, text, reply_markup)

    async def send_document(self, chat_id, document, caption=None, **_) -> None:
        self.documents.append((chat_id, document.filename, document.data))


async def test_copy_goes_to_the_head_admin(tmp_path: Path, monkeypatch):
    async def fake_dump(url: str) -> bytes:
        return gzip.compress(b"-- dump")

    async def chats() -> set[int]:
        return {42}

    monkeypatch.setattr(backup, "dump", fake_dump)
    monkeypatch.setattr(loops, "admin_chats", chats)
    bot = DocumentBot()

    path = await loops.backup_if_due(bot, tmp_path, now=at(22, 4, 30))

    assert path is not None and path.exists()
    assert bot.documents == [(42, path.name, path.read_bytes())]
    # Второй проход в тот же день ничего не снимает и не шлёт.
    assert await loops.backup_if_due(bot, tmp_path, now=at(22, 16)) is None
    assert len(bot.documents) == 1


async def test_dump_failure_is_reported_with_its_reason(monkeypatch):
    """pg_dump пишет причину в stderr — она должна дойти до админа, а не
    превратиться в «что-то пошло не так»."""

    class Process:
        returncode = 1

        async def communicate(self):
            return b"", b"pg_dump: error: connection refused"

    async def spawn(*args, **kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    try:
        await backup.dump("postgresql+asyncpg://cinema:secret@db:5432/cinema")
    except backup.BackupError as exc:
        assert "connection refused" in str(exc)
    else:
        raise AssertionError("ошибка pg_dump потерялась")


async def test_password_is_not_in_the_arguments(monkeypatch):
    seen = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b"-- dump", b""

    async def spawn(*args, **kwargs):
        seen["args"], seen["env"] = args, kwargs["env"]
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    data = await backup.dump("postgresql+asyncpg://cinema:secret@db:5432/cinema")

    assert gzip.decompress(data) == b"-- dump"
    assert "secret" not in " ".join(seen["args"])
    assert seen["env"]["PGPASSWORD"] == "secret"
    assert seen["args"][seen["args"].index("-d") + 1] == "cinema"


# --- Сторож -----------------------------------------------------------------


def test_pulse_counts_failures_in_a_row():
    pulse = loops.Pulse("задачи", stale_after=60)
    pulse.beat("упало")
    pulse.beat("упало снова")
    assert pulse.failures == 2 and pulse.last_error == "упало снова"
    pulse.beat()
    assert pulse.failures == 0


async def test_watchdog_raises_the_alarm_and_stops_on_a_stuck_loop(monkeypatch):
    messages: list[str] = []

    async def alarm(bot, text: str) -> None:
        messages.append(text)

    monkeypatch.setattr(loops, "alarm", alarm)
    monkeypatch.setattr(loops, "WATCHDOG_INTERVAL_SECONDS", 0.01)
    stuck = loops.Pulse("фоновые задачи клуба", stale_after=60)
    stuck.last_beat -= 3600

    await asyncio.wait_for(loops.watchdog(None, (stuck,)), timeout=2)

    assert len(messages) == 1
    assert "фоновые задачи клуба" in messages[0] and "Перезапускаюсь" in messages[0]


async def test_watchdog_reports_a_failing_loop_once(monkeypatch, tmp_path: Path):
    messages: list[str] = []

    async def alarm(bot, text: str) -> None:
        messages.append(text)

    monkeypatch.setattr(loops, "alarm", alarm)
    monkeypatch.setattr(loops, "WATCHDOG_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(loops, "HEARTBEAT_FILE", tmp_path / "alive")
    failing = loops.Pulse("рассылка", stale_after=60, alert_after=3)
    for _ in range(3):
        failing.beat("ConnectionRefusedError: база недоступна")

    task = asyncio.create_task(loops.watchdog(None, (failing,)))
    await asyncio.sleep(0.1)
    failing.beat("ConnectionRefusedError: база недоступна")
    await asyncio.sleep(0.1)
    task.cancel()

    assert len(messages) == 1, "об одной серии сбоев пишем один раз"
    assert "база недоступна" in messages[0]
    assert (tmp_path / "alive").exists()


async def test_a_loop_marks_its_pulse(monkeypatch):
    monkeypatch.setattr(loops, "JOB_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(loops, "JOBS_INTERVAL_SECONDS", 0.01)

    async def broken(session):
        raise RuntimeError("сломалось")

    monkeypatch.setattr(loops.cycle, "tick", broken)
    loops.JOBS.beat()
    task = asyncio.create_task(loops.jobs_loop())
    await asyncio.sleep(0.2)
    task.cancel()

    assert loops.JOBS.failures >= 2
    assert "сломалось" in loops.JOBS.last_error
    loops.JOBS.beat()


def test_catch_all_reply_is_the_last_router():
    """Ответ «на всё остальное», стоящий раньше, глотал бы /analytics и пароль."""
    routers = build_dispatcher().sub_routers
    assert routers[-1].name == "fallback"


# --- Заблокировавшие бота ---------------------------------------------------


async def test_blocking_the_bot_is_remembered(session):
    user = await make_user(session, "Заблокировал")
    await session.commit()
    for key in ("a", "b"):
        await notify.queue(session, user.id, NotificationKind.REMINDER_2H, key, {})
    await session.commit()

    bot = FakeBot(fail_for={user.tg_id})
    await notify.deliver(session, bot, moscow)

    await session.refresh(user)
    assert user.bot_blocked_at is not None
    reasons = sorted(
        (await session.scalars(sa.select(Notification.failed_reason))).all()
    )
    # Второе сообщение даже не пробовали: отказ был заведомый.
    assert "заблокировал бота" in reasons


async def test_blocked_people_are_not_counted_as_recipients(session):
    await make_user(session, "Слушает")
    gone = await make_user(session, "Заблокировал")
    gone.bot_blocked_at = datetime.now(UTC)
    await session.commit()

    assert await broadcast.audience_size(session, broadcast.ALL) == 1


async def test_a_month_later_we_try_again(session):
    """Разблокировать можно и молча — тогда пометка сама не снимется."""
    user = await make_user(session, "Вернулся")
    user.bot_blocked_at = datetime.now(UTC) - timedelta(days=31)
    await session.commit()
    await notify.queue(session, user.id, NotificationKind.REMINDER_2H, "k", {})
    await session.commit()

    bot = FakeBot()
    assert await notify.deliver(session, bot, moscow) == 1


async def test_writing_to_the_bot_lifts_the_mark(session):
    from types import SimpleNamespace

    from app.bot.common import ensure_user

    user = await make_user(session, "Вернулся")
    user.bot_blocked_at = datetime.now(UTC)
    await session.commit()

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=user.tg_id, username=None, first_name="В", last_name=None)
    )
    await ensure_user(session, message)
    fresh = await session.scalar(sa.select(User).where(User.id == user.id))
    assert fresh.bot_blocked_at is None
