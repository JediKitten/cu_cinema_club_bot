"""То, что нужно всем частям бота: адрес приложения и «кто это написал»."""

import sqlalchemy as sa
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.config import get_config
from app.db import SessionLocal
from app.models import User


def current_miniapp_url() -> str:
    """Адрес читается при каждом обращении, а не один раз на старте.

    В разработке он живёт в туннеле и меняется при каждом перезапуске. Пока
    значение сидело в замыкании, бот после смены адреса продолжал раздавать
    кнопку на мёртвый туннель, и это выглядело как «бот не работает».
    """
    get_config.cache_clear()
    return get_config().miniapp_url


def app_button(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))


def open_app_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[app_button("🎬 Открыть киноклуб", url)]])


async def ensure_user(session, message: Message) -> User:
    """Аккаунт может ещё не существовать: человек написал боту, не открыв
    приложение. Заводим сразу — иначе ни приглашение засчитать, ни запомнить,
    что знакомство уже показывали.

    Написал боту — значит, снова его слышит: пометку «заблокировал бота»
    снимаем здесь же, иначе рассылки обходили бы вернувшегося стороной.
    """
    tg_id = message.from_user.id
    user = (
        await session.execute(sa.select(User).where(User.tg_id == tg_id))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            tg_id=tg_id,
            tg_username=message.from_user.username,
            display_name=" ".join(
                filter(None, (message.from_user.first_name, message.from_user.last_name))
            )
            or f"user{tg_id}",
        )
        session.add(user)
        await session.commit()
    elif user.bot_blocked_at is not None:
        user.bot_blocked_at = None
        await session.commit()
    return user


async def user_id(session, tg_id: int) -> int | None:
    """Кто это в наших терминах. Может не найтись: /analytics бывает нужна
    и тому, кто в клубе не состоит, — на аудит это не влияет, tg_id в записи
    остаётся в любом случае."""
    return await session.scalar(sa.select(User.id).where(User.tg_id == tg_id))


async def mark_onboarded(tg_id: int) -> None:
    async with SessionLocal() as session:
        await session.execute(
            sa.update(User)
            .where(User.tg_id == tg_id, User.onboarded_at.is_(None))
            .values(onboarded_at=sa.func.now())
        )
        await session.commit()
