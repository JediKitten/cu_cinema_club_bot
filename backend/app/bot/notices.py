"""Кнопки под уведомлениями из очереди.

Сервис рассылки о Telegram не знает — клавиатуру к сообщению собирает бот.
"""

from aiogram.types import InlineKeyboardMarkup

from app.bot import common
from app.bot.votes import shortlist_keyboard
from app.models.enums import NotificationKind


def survey_keyboard(screening_id: int | None) -> InlineKeyboardMarkup | None:
    """Кнопка к напоминанию об опросе — сразу в форму нужного показа.

    Без неё сообщение зовёт «оценить в приложении», а приложение открывается
    на каталоге: форму надо ещё найти, и половина людей до неё не доходит.
    """
    url = common.current_miniapp_url()
    if not screening_id or not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[common.app_button("⭐️ Оценить показ", f"{url}?survey={screening_id}")]]
    )


def notify_keyboard(kind: NotificationKind, payload: dict) -> InlineKeyboardMarkup | None:
    """Кнопка приложения там, где сообщение зовёт зайти."""
    if kind == NotificationKind.SHORTLIST_PUBLISHED:
        return shortlist_keyboard(payload)
    if kind == NotificationKind.FEEDBACK_REMINDER:
        return survey_keyboard(payload.get("screening_id"))
    return None
