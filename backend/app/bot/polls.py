"""Опросы кнопками под сообщением бота — кнопки и приём ответов.

Реестр опросов и подсчёт итогов — в app/services/polls.py: итоги нужны и
админке, а она о Telegram не знает.
"""

import sqlalchemy as sa
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db import SessionLocal
from app.models import User
from app.services.polls import POLLS, poll_text, record, results

__all__ = ["POLLS", "poll_keyboard", "poll_text", "results", "router"]


def poll_keyboard(key: str, chosen: int | None = None) -> InlineKeyboardMarkup | None:
    poll = POLLS.get(key)
    if poll is None:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ {label}" if index == chosen else label,
                    callback_data=f"poll:{key}:{index}",
                )
            ]
            for index, label in enumerate(poll.buttons)
        ]
    )


router = Router(name="polls")


@router.callback_query(F.data.startswith("poll:"))
async def answer(callback: CallbackQuery) -> None:
    _, key, raw = (callback.data.split(":") + ["", ""])[:3]
    poll = POLLS.get(key)
    if poll is None or not raw.isdigit() or int(raw) >= len(poll.options):
        await callback.answer("Этот опрос уже закрыт")
        return
    option = int(raw)

    async with SessionLocal() as session:
        user_id = await session.scalar(
            sa.select(User.id).where(User.tg_id == callback.from_user.id)
        )
        if user_id is None:
            await callback.answer("Сначала напишите боту /start", show_alert=True)
            return
        session.add(record(user_id, key, option, callback.from_user.id))
        await session.commit()

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=poll_keyboard(key, option))
        except TelegramBadRequest:
            # Нажал тот же вариант второй раз — клавиатура уже такая.
            pass
    await callback.answer("Спасибо, ответ учтён!")
