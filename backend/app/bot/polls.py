"""Короткие опросы кнопками под сообщением бота.

Нативный опрос Telegram здесь не годится: в личку каждому уходит своё
сообщение, и у каждого получился бы отдельный опрос со своим итогом —
сложить их нельзя. Поэтому варианты — кнопки, а каждое нажатие ложится
в журнал аудита: итог по всем считается одним запросом (`results`).

Передумать можно: засчитывается последний ответ человека.
"""

from dataclasses import dataclass

import sqlalchemy as sa
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import AuditLog, User

ENTITY = "poll"


@dataclass(frozen=True, slots=True)
class Poll:
    question: str
    # Полные формулировки — в тексте сообщения, на кнопках — короткие:
    # длинную подпись Telegram обрезает посреди слова.
    options: tuple[str, ...]
    buttons: tuple[str, ...]


POLLS: dict[str, Poll] = {
    "wolf-day": Poll(
        question=(
            "В связи с накладками в расписании кинозала мы стоим перед выбором, "
            "что было бы вам предпочтительнее?"
        ),
        options=(
            "Просмотр «Волка с Уолл-стрит» в четверг в кинотеатре",
            "Просмотр «Волка с Уолл-стрит» в пятницу (там посвят цуеты...) в одной "
            "из аудиторий (притащим пуфики, запустим на экранах)",
        ),
        buttons=("1️⃣ Четверг, кинотеатр", "2️⃣ Пятница, аудитория"),
    ),
}


def poll_text(key: str) -> str:
    poll = POLLS[key]
    lines = [poll.question, ""]
    lines += [f"{number}. {option}" for number, option in enumerate(poll.options, 1)]
    lines += ["", "Ответьте кнопкой ниже — передумать можно, засчитается последний ответ."]
    return "\n".join(lines)


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


async def results(session: AsyncSession, key: str) -> list[int]:
    """Сколько человек выбрали каждый вариант — по последнему ответу каждого."""
    latest = (
        sa.select(
            AuditLog.actor_id,
            AuditLog.payload["option"].as_integer().label("option"),
            sa.func.row_number()
            .over(partition_by=AuditLog.actor_id, order_by=AuditLog.id.desc())
            .label("rank"),
        )
        .where(AuditLog.entity == ENTITY, AuditLog.action == key)
        .subquery()
    )
    counts = dict(
        (
            await session.execute(
                sa.select(latest.c.option, sa.func.count())
                .where(latest.c.rank == 1)
                .group_by(latest.c.option)
            )
        ).all()
    )
    return [counts.get(index, 0) for index in range(len(POLLS[key].options))]


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
        session.add(
            AuditLog(
                actor_id=user_id,
                entity=ENTITY,
                action=key,
                payload={"option": option, "tg_id": callback.from_user.id},
            )
        )
        await session.commit()

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=poll_keyboard(key, option))
        except TelegramBadRequest:
            # Нажал тот же вариант второй раз — клавиатура уже такая.
            pass
    await callback.answer("Спасибо, ответ учтён!")
