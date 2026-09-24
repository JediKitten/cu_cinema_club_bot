"""Голосование кнопками под уведомлением о шорт-листе.

Приглашение голосовать приходило с одной просьбой: «отметьте в приложении».
Между ней и голосом стояли три действия — открыть Mini App, дождаться
загрузки, найти вкладку, — и половина людей до голоса не доходила. Кнопка
под сообщением превращает голос в одно нажатие, не выходя из переписки.
Вечера всё равно выбирают в приложении: семь дат кнопками в чате читаются
хуже, чем сеткой на экране.
"""

import asyncio

import sqlalchemy as sa
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import common
from app.db import SessionLocal
from app.models import Round, User
from app.services import voting

# Длинное название Telegram обрежет и сам, но по-своему — посреди слова
# и без многоточия.
BUTTON_TITLE_LIMIT = 28

# Нажатия идут подряд: человек отмечает три фильма за секунду. Обработчики
# aiogram выполняются параллельно, и без замка второй успевал бы перерисовать
# клавиатуру по состоянию, снятому до первого, — галочка «отскакивала» бы
# обратно, а следующее нажатие снимало бы уже поставленный голос.
_vote_locks: dict[int, asyncio.Lock] = {}


def _vote_lock(tg_id: int) -> asyncio.Lock:
    return _vote_locks.setdefault(tg_id, asyncio.Lock())


def _short(title: str) -> str:
    return title if len(title) <= BUTTON_TITLE_LIMIT else title[: BUTTON_TITLE_LIMIT - 1] + "…"


def vote_keyboard(
    round_id: int,
    films: list[tuple[int, str]],
    chosen: set[int],
    week_start: str | None = None,
) -> InlineKeyboardMarkup:
    """Кнопка на фильм плюс — когда выбран хоть один — вход в приложение.

    Кнопка приложения появляется не сразу намеренно: пока человек ничего
    не отметил, звать его выбирать вечера рано, а лишняя кнопка внизу
    перетягивает нажатие на себя.
    """
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if film_id in chosen else '▫️'} {_short(title)}",
                callback_data=f"v:{round_id}:{film_id}",
            )
        ]
        for film_id, title in films
    ]

    url = common.current_miniapp_url()
    if chosen and url:
        # Неделя в адресе обязательна: без неё приложение открывает расписание
        # текущей недели, и до бюллетеня остаётся ещё одно нажатие — ровно то,
        # ради избавления от которого кнопки и заводили.
        week = f"&week={week_start}" if week_start else ""
        rows.append(
            [common.app_button("📅 Теперь отметьте свободные вечера", f"{url}?tab=vote{week}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shortlist_keyboard(payload: dict) -> InlineKeyboardMarkup | None:
    """Клавиатура к уведомлению о шорт-листе.

    Старые записи в очереди хранят голые названия без id — кнопок к ним
    не собрать, и сообщение уйдёт как раньше, просто текстом.
    """
    round_id = payload.get("round_id")
    films = [
        (int(film["id"]), str(film.get("title", "")))
        for film in (payload.get("films") or [])
        if isinstance(film, dict) and film.get("id")
    ]
    if not round_id or not films:
        return None
    # В рассылке обновлённого списка у каждого свои галочки: кнопка
    # переключает голос, и без них нажатие на уже выбранный фильм снимало бы
    # голос, хотя человек думал, что голосует.
    chosen = {int(film_id) for film_id in payload.get("chosen") or []}
    return vote_keyboard(int(round_id), films, chosen, payload.get("week_start"))


router = Router(name="votes")


@router.callback_query(F.data.startswith("v:"))
async def vote_button(callback: CallbackQuery) -> None:
    """Нажатие на фильм — это голос: тот же, что ставят в приложении."""
    parts = callback.data.split(":")
    if len(parts) != 3 or not all(part.isdigit() for part in parts[1:]):
        await callback.answer("Не разобрал кнопку")
        return
    round_id, film_id = int(parts[1]), int(parts[2])

    # Пока один обработчик считает выбор, второй не должен рисовать
    # клавиатуру по устаревшему: люди отмечают фильмы подряд, не дожидаясь
    # ответа на предыдущее нажатие.
    async with _vote_lock(callback.from_user.id):
        async with SessionLocal() as session:
            user = (
                await session.execute(sa.select(User).where(User.tg_id == callback.from_user.id))
            ).scalar_one_or_none()
            if user is None:
                await callback.answer("Сначала напишите боту /start", show_alert=True)
                return
            round_ = await session.get(Round, round_id)
            try:
                voting.ensure_open(round_)
                now_on, chosen = await voting.toggle_vote(session, round_, user.id, film_id)
                gone = False
            except voting.FilmNotInShortlist:
                # Фильм убрали из шорт-листа после публикации, а кнопка
                # осталась в старом сообщении. Мало сказать «нет в списке» —
                # клавиатуру надо обновить, иначе следующее нажатие упрётся
                # в ту же стену.
                now_on, chosen, gone = False, await voting.my_votes(session, round_, user.id), True
            except voting.VotingError as exc:
                await callback.answer(str(exc), show_alert=True)
                return

            films = [
                (film.id, film.title_ru) for film in await voting.shortlist_films(session, round_)
            ]
            week_start = round_.week_start.isoformat()

    # Сообщение может оказаться недоступным — например, человек его удалил.
    # Голос при этом уже засчитан, и жаловаться не на что.
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(
                reply_markup=vote_keyboard(round_id, films, set(chosen), week_start)
            )
        except TelegramBadRequest:
            # Клавиатура уже такая же — для человека ничего не произошло.
            pass

    if gone:
        await callback.answer(
            "Этот фильм убрали из шорт-листа. Список под сообщением обновлён.", show_alert=True
        )
    elif not now_on:
        await callback.answer("Убрал из выбранных")
    elif len(chosen) == 1:
        # Первая галочка — тот момент, когда про вечера уместно сказать
        # словами: кнопка под сообщением только что появилась, и без
        # подсказки её легко принять за часть списка фильмов.
        await callback.answer("Отметил. Осталось выбрать вечера — кнопка внизу")
    else:
        await callback.answer("Отметил")
