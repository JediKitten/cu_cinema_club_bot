"""Выгрузка данных в Excel по паролю (§14, расширение по просьбе клуба).

В /help команды нет намеренно. Она не секретная — без пароля она ничего
не отдаёт, — но строка «/analytics — выгрузить базу клуба» в справке у всех
подряд только подсказывает, что именно стоит попробовать подобрать. Кому
выгрузка нужна, тот получает пароль вместе с названием команды.
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot import common
from app.db import SessionLocal
from app.models import AuditLog
from app.services import analytics_gate, exports
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)


class AnalyticsGate(StatesGroup):
    waiting_password = State()


# Кто уже ввёл пароль — в памяти процесса. Почему не в базе — см.
# services/analytics_gate.py: состояние живёт полчаса и переживать перезапуск
# не должно.
ANALYTICS_ACCESS = analytics_gate.AccessGate()

ANALYTICS_OFF = (
    "📊 <b>Выгрузка данных</b>\n\n"
    "Пока выключена: администратор не задал пароль.\n\n"
    "Он ставится в приложении — «Ещё» → «⚙ Клуб» → «Аналитика» → «Выгрузка в Excel»."
)

ANALYTICS_ASK = (
    "📊 <b>Выгрузка данных</b>\n\n"
    "Отправьте пароль одним сообщением — я его сразу удалю из переписки.\n"
    "Пароль выдаёт администратор клуба.\n\n"
    "/cancel — выйти."
)

ANALYTICS_CANCELLED = "Ввод пароля отменён."

ANALYTICS_WRONG = "Пароль не подошёл. Осталось попыток: {left}."

ANALYTICS_EXPIRED = "Доступ истёк — наберите /analytics заново"


def minutes_left(delta) -> int:
    """Округляем вверх: «подождите 0 минут» — это издевательство, а не ответ."""
    return max(1, -(-int(delta.total_seconds()) // 60))


def analytics_menu_text() -> str:
    lines = [
        "📊 <b>Выгрузка данных</b>",
        "",
        "Каждая кнопка — отдельный файл Excel.",
        "",
    ]
    lines += [
        f"{dataset.title} — {dataset.summary}" for dataset in exports.DATASETS
    ]
    lines += [
        "",
        "📦 <b>Всё сразу</b> — одна книга, в ней все листы разом.",
        "",
        f"<i>Доступ открыт на {int(analytics_gate.UNLOCK_TTL.total_seconds() // 60)} минут "
        "и продлевается с каждой выгрузкой.</i>",
    ]
    return "\n".join(lines)


def analytics_keyboard() -> InlineKeyboardMarkup:
    """Наборы по два в ряд, «всё» — отдельной строкой во всю ширину:
    это другой по смыслу шаг, и попасть в него случайно не должно."""
    buttons = [
        InlineKeyboardButton(text=dataset.title, callback_data=f"dl:{dataset.key}")
        for dataset in exports.DATASETS
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append(
        [
            InlineKeyboardButton(
                text="📦 Выгрузить всё одной книгой",
                callback_data=f"dl:{exports.EVERYTHING}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


router = Router(name="export")


@router.message(Command("analytics"))
async def analytics_command(message: Message, state: FSMContext) -> None:
    """Выгрузка таблиц клуба. Роль здесь не спрашивается намеренно.

    Таблицы регулярно нужны тем, кому админка не нужна вовсе — руководству
    клуба, вузу. Раздавать ради выгрузки роль админа значит раздавать
    заодно отмену показов и правку параметров, поэтому дверь отдельная
    и запирается отдельным паролем.
    """
    async with SessionLocal() as session:
        if not await analytics_gate.is_set(session):
            await state.clear()
            await message.answer(ANALYTICS_OFF)
            return

    tg_id = message.from_user.id
    if ANALYTICS_ACCESS.is_unlocked(tg_id):
        await state.clear()
        await message.answer(analytics_menu_text(), reply_markup=analytics_keyboard())
        return

    wait = ANALYTICS_ACCESS.locked_for(tg_id)
    if wait is not None:
        await state.clear()
        await message.answer(
            f"Слишком много неверных попыток. Попробуйте через {minutes_left(wait)} мин."
        )
        return

    await state.set_state(AnalyticsGate.waiting_password)
    await message.answer(ANALYTICS_ASK)

@router.message(AnalyticsGate.waiting_password)
async def analytics_password(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        # Команду, набранную вместо пароля, нельзя принимать за пароль:
        # человек передумал, а не ошибся.
        await state.clear()
        await message.answer(ANALYTICS_CANCELLED)
        return

    # Пароль, оставшийся в переписке, — это пароль, который прочтут через
    # плечо. В личке бот вправе удалять входящие, поэтому удаляем.
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    tg_id = message.from_user.id
    wait = ANALYTICS_ACCESS.locked_for(tg_id)
    if wait is not None:
        await state.clear()
        await message.answer(
            f"Слишком много неверных попыток. Попробуйте через {minutes_left(wait)} мин."
        )
        return

    async with SessionLocal() as session:
        stored = await analytics_gate.stored_hash(session)
        # PBKDF2 на 600 тысяч итераций считается четверть секунды — в общем
        # цикле это заодно четверть секунды задержки всей рассылки.
        matched = await asyncio.to_thread(analytics_gate.verify, stored, text)
        if matched:
            session.add(
                AuditLog(
                    actor_id=await common.user_id(session, tg_id),
                    entity="analytics_export",
                    action="unlock",
                    payload={"tg_id": tg_id},
                )
            )
            await session.commit()

    if not matched:
        left = ANALYTICS_ACCESS.register_failure(tg_id)
        if left == 0:
            await state.clear()
            await message.answer(
                "Пароль не подошёл. Попытки кончились — следующая через "
                f"{minutes_left(analytics_gate.LOCKOUT)} мин."
            )
            return
        await message.answer(ANALYTICS_WRONG.format(left=left))
        return

    ANALYTICS_ACCESS.unlock(tg_id)
    await state.clear()
    await message.answer(analytics_menu_text(), reply_markup=analytics_keyboard())

@router.callback_query(F.data.startswith("dl:"))
async def analytics_download(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 1)[1]
    tg_id = callback.from_user.id

    if not ANALYTICS_ACCESS.is_unlocked(tg_id):
        await callback.answer(ANALYTICS_EXPIRED, show_alert=True)
        return
    if key != exports.EVERYTHING and key not in exports.BY_KEY:
        await callback.answer("Такой выгрузки нет")
        return

    await callback.answer("Собираю файл…")
    try:
        await callback.bot.send_chat_action(callback.message.chat.id, "upload_document")

        async with SessionLocal() as session:
            tz = ZoneInfo(str(await SettingsService(session).get("display_timezone")))
            sheets = await exports.build(session, key)
            session.add(
                AuditLog(
                    actor_id=await common.user_id(session, tg_id),
                    entity="analytics_export",
                    action=key,
                    payload={"tg_id": tg_id},
                )
            )
            await session.commit()

        # Сборка книги — чистый процессор, и на «всё сразу» это секунды.
        # В общем цикле они остановили бы заодно и рассылку уведомлений.
        data = await asyncio.to_thread(exports.workbook, sheets, tz)
    except Exception:
        logger.exception("Не удалось собрать выгрузку %s", key)
        await callback.message.answer(
            "Не получилось собрать файл. Попробуйте ещё раз или напишите администратору."
        )
        return

    title = "📦 Всё сразу" if key == exports.EVERYTHING else exports.BY_KEY[key].title
    rows = sum(len(sheet.rows) for sheet in sheets)
    await callback.message.answer_document(
        BufferedInputFile(data, exports.filename(key, datetime.now(tz))),
        caption=f"{title}\nЛистов: {len(sheets)}, строк: {rows}",
    )
    # Качают обычно не один файл: каждая выгрузка продлевает доступ, иначе
    # он истёк бы на середине пачки.
    ANALYTICS_ACCESS.unlock(tg_id)
