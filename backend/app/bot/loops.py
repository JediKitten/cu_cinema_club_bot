"""Фоновая работа бота: рассылка, задачи клуба, ночная копия базы — и сторож над ними.

Каждый цикл по завершении прохода отмечается в своём `Pulse`. Сторож раз
в минуту смотрит на отметки и делает две вещи, которых раньше не было:

* цикл давно не отмечался — значит, он встал так, что таймаут не спас
  (например, завис сам event loop). Сторож пишет главному админу и завершает
  процесс; Docker поднимает его заново (`restart: unless-stopped`);
* цикл отмечается, но каждый проход падает — сторож пишет главному админу
  один раз на серию, с текстом последней ошибки.

Однажды цикл клуба уже простоял восемнадцать часов, и узнали об этом по
симптомам. Теперь о таком узнают из сообщения, а чаще — не узнают вовсе,
потому что перезапуск чинит его сам.
"""

import asyncio
import logging
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.bot.notices import notify_keyboard
from app.config import get_config
from app.db import SessionLocal
from app.models import User
from app.models.enums import UserRole
from app.services import achievements, backup, cycle, notify, reminders, tournaments
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Очередь уведомлений разгребается часто: приглашение после публикации должно
# приходить сразу, а не через минуты.
NOTIFY_INTERVAL_SECONDS = 5

# Напоминания и предупреждения о недоборе. Окно допуска в reminders.py — полчаса,
# поэтому проход раз в пять минут ничего не пропускает.
JOBS_INTERVAL_SECONDS = 300

# Копия снимается раз в сутки, но проверять, не пора ли, надо чаще: бот мог
# быть выключен в назначенный час.
BACKUP_CHECK_SECONDS = 600

# Сколько даём одному проходу, прежде чем считать его зависшим. Фоновые задачи
# ходят только в базу, и минуты им хватает с большим запасом. Ограничение нужно
# не ради скорости: зависший `await` не бросает исключения, и `except Exception`
# вокруг тела цикла его не ловит — задача просто перестаёт существовать. Именно
# так однажды тихо встал весь цикл клуба: уведомления продолжали уходить, а
# расписание, ачивки и напоминания не двигались восемнадцать часов, и ни одной
# строчки в логе об этом не было.
JOB_TIMEOUT_SECONDS = 120
NOTIFY_TIMEOUT_SECONDS = 120
BACKUP_TIMEOUT_SECONDS = 600

WATCHDOG_INTERVAL_SECONDS = 60

# Файл-пульс для healthcheck контейнера: обновляется, пока все циклы живы.
HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "cinema-bot-alive"

# Больше этого Telegram от бота документ не примет.
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024


@dataclass
class Pulse:
    """Последний признак жизни одного цикла."""

    title: str
    # Сколько секунд тишины уже не объяснить длинным проходом: интервал
    # плюс таймаут прохода плюс запас.
    stale_after: float
    # После скольких падений подряд звать человека. У рассылки порог выше:
    # она ходит раз в пять секунд, и минутная перезагрузка базы — это десяток
    # падений, о которых писать незачем.
    alert_after: int = 3
    last_beat: float = field(default_factory=time.monotonic)
    failures: int = 0
    last_error: str = ""
    alerted: bool = False

    def beat(self, error: str | None = None) -> None:
        self.last_beat = time.monotonic()
        if error is None:
            self.failures = 0
            self.alerted = False
        else:
            self.failures += 1
            self.last_error = error

    def silent_for(self, now: float | None = None) -> float:
        return (now if now is not None else time.monotonic()) - self.last_beat

    def is_stale(self, now: float | None = None) -> bool:
        return self.silent_for(now) > self.stale_after


NOTIFY = Pulse("рассылка уведомлений", stale_after=600, alert_after=12)
JOBS = Pulse("фоновые задачи клуба", stale_after=900)
BACKUP = Pulse("ночная копия базы", stale_after=1800)


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


# --- Связь с главным админом -------------------------------------------------


async def admin_chats() -> set[int]:
    """Кому писать о сбоях. Адрес из .env — на случай, когда лежит сама база
    и спросить её, кто главный админ, нельзя."""
    chats: set[int] = set()
    if (bootstrap := get_config().bootstrap_superadmin_tg_id) is not None:
        chats.add(bootstrap)
    try:
        async with asyncio.timeout(5):
            async with SessionLocal() as session:
                rows = await session.scalars(
                    sa.select(User.tg_id).where(
                        User.role == UserRole.SUPERADMIN, User.tg_id.is_not(None)
                    )
                )
                chats.update(rows)
    except Exception:
        logger.warning("Не удалось узнать главных админов из базы — пишу по .env")
    return chats


async def alarm(bot: Bot, text: str) -> None:
    """Сообщение главному админу о сбое. Не через очередь уведомлений: она
    сама может быть тем, что сломалось."""
    logger.error("Тревога: %s", text)
    for chat in await admin_chats():
        try:
            async with asyncio.timeout(15):
                await bot.send_message(chat, text, parse_mode=None)
        except Exception:
            logger.exception("Не удалось отправить тревогу в %s", chat)


async def watchdog(bot: Bot, pulses: tuple[Pulse, ...] = (NOTIFY, JOBS, BACKUP)) -> None:
    """Возвращается, когда какой-то цикл встал: вызывающий завершает процесс."""
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
        now = time.monotonic()

        stale = [pulse for pulse in pulses if pulse.is_stale(now)]
        if stale:
            names = ", ".join(
                f"{pulse.title} (молчит {int(pulse.silent_for(now) // 60)} мин)" for pulse in stale
            )
            await alarm(bot, f"⚠️ Бот киноклуба: встало — {names}. Перезапускаюсь.")
            return

        for pulse in pulses:
            if pulse.failures >= pulse.alert_after and not pulse.alerted:
                pulse.alerted = True
                await alarm(
                    bot,
                    f"⚠️ Бот киноклуба: {pulse.title} — {pulse.failures} сбоев подряд.\n"
                    f"Последняя ошибка: {pulse.last_error}",
                )

        try:
            HEARTBEAT_FILE.touch()
        except OSError:
            logger.warning("Не удалось обновить %s", HEARTBEAT_FILE)


# --- Циклы -------------------------------------------------------------------


async def _club_tz(session) -> ZoneInfo:
    return ZoneInfo(str(await SettingsService(session).get("display_timezone")))


async def notification_loop(bot: Bot) -> None:
    """Отправляет накопившиеся уведомления.

    Отдельно от их создания: так падение бота не теряет уведомление — оно
    просто уйдёт следующим проходом.
    """
    while True:
        error = None
        try:
            async with asyncio.timeout(NOTIFY_TIMEOUT_SECONDS):
                async with SessionLocal() as session:
                    tz = await _club_tz(session)

                    def to_local(value: datetime, tz: ZoneInfo = tz) -> str:
                        return value.astimezone(tz).strftime("%d.%m в %H:%M")

                    sent = await notify.deliver(session, bot, to_local, keyboard=notify_keyboard)
                    if sent:
                        logger.info("Отправлено уведомлений: %d", sent)
        except TimeoutError:
            error = "проход завис дольше таймаута"
            logger.error("Отправка уведомлений зависла — прерываю проход")
        except Exception as exc:
            # Цикл обязан пережить любую ошибку: иначе одна неудача навсегда
            # останавливает всю рассылку.
            error = _describe(exc)
            logger.exception("Сбой при отправке уведомлений")
        NOTIFY.beat(error)
        await asyncio.sleep(NOTIFY_INTERVAL_SECONDS)


async def jobs_loop() -> None:
    """Периодические задачи: напоминания, предупреждения о недоборе (§7)."""
    while True:
        error = None
        try:
            # Таймаут снаружи всего прохода: повиснуть может любой из четырёх
            # шагов, а починка одна — прервать и попробовать через пять минут.
            async with asyncio.timeout(JOB_TIMEOUT_SECONDS):
                async with SessionLocal() as session:
                    # Порядок важен: сначала двигаем цикл, потом рассылаем —
                    # иначе приглашения после автопубликации ждали бы лишние
                    # пять минут.
                    await cycle.tick(session)
                    await tournaments.tick(session)
                    await achievements.award(session)
                    await reminders.run_all(session)
        except TimeoutError:
            error = "проход завис дольше таймаута"
            logger.error("Фоновые задачи зависли — прерываю проход")
        except Exception as exc:
            error = _describe(exc)
            logger.exception("Сбой в фоновых задачах")
        JOBS.beat(error)
        await asyncio.sleep(JOBS_INTERVAL_SECONDS)


async def backup_if_due(bot: Bot, directory: Path, now: datetime | None = None) -> Path | None:
    """Снимает копию, если сегодняшней ещё нет, и отправляет её главному админу."""
    if now is None:
        async with SessionLocal() as session:
            now = datetime.now(await _club_tz(session))
    if not backup.is_due(directory, now):
        return None

    data = await backup.dump(get_config().database_url)
    path = backup.save(directory, backup.filename(now), data)
    removed = backup.rotate(directory)
    logger.info(
        "Копия базы: %s, %.1f МБ; удалено старых: %d", path.name, len(data) / 2**20, len(removed)
    )

    # Копия на том же сервере — не копия: диск умрёт вместе с базой.
    # Telegram главного админа — место за пределами сервера, которое уже есть.
    if len(data) > TELEGRAM_FILE_LIMIT:
        await alarm(
            bot,
            f"🗄 Копия базы {path.name} ({len(data) / 2**20:.0f} МБ) больше лимита Telegram — "
            "она есть только на сервере. Пора завести внешнее хранилище.",
        )
        return path

    caption = (
        f"🗄 Копия базы киноклуба за {now:%d.%m.%Y}, {len(data) / 2**20:.1f} МБ.\n"
        "Внутри все данные клуба — не пересылайте.\n"
        "Как восстановить — deploy/README.md, «Бэкап и восстановление»."
    )
    for chat in await admin_chats():
        try:
            await bot.send_document(
                chat, BufferedInputFile(data, path.name), caption=caption, parse_mode=None
            )
        except Exception:
            # Копия на сервере уже есть — неудача доставки не повод снимать её
            # заново через десять минут.
            logger.exception("Не удалось отправить копию базы в %s", chat)
    return path


async def backup_loop(bot: Bot, directory: Path) -> None:
    while True:
        error = None
        try:
            async with asyncio.timeout(BACKUP_TIMEOUT_SECONDS):
                await backup_if_due(bot, directory)
        except TimeoutError:
            error = "pg_dump не уложился в таймаут"
            logger.error("Копия базы не снялась за %d с", BACKUP_TIMEOUT_SECONDS)
        except Exception as exc:
            error = _describe(exc)
            logger.exception("Не удалось снять копию базы")
        BACKUP.beat(error)
        await asyncio.sleep(BACKUP_CHECK_SECONDS)
