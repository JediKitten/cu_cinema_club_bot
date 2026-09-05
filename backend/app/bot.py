"""Telegram-бот (§12, §17).

Пока делает одно: пускает в Mini App и объясняет, что это такое. Уведомления
этапов 3–4 и ввод кода присутствия появятся здесь же.

Запуск: ./venv/bin/python -m app.bot
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from app.config import get_config
from app.db import SessionLocal
from app.services import cycle, notify, reminders
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Как часто перечитывать .env в поисках нового адреса туннеля.
URL_WATCH_INTERVAL_SECONDS = 5

# Очередь уведомлений разгребается часто: приглашение после публикации должно
# приходить сразу, а не через минуты.
NOTIFY_INTERVAL_SECONDS = 5

# Напоминания и предупреждения о недоборе. Окно допуска в reminders.py — полчаса,
# поэтому проход раз в пять минут ничего не пропускает.
JOBS_INTERVAL_SECONDS = 300

WELCOME = (
    "<b>Университетский киноклуб</b>\n\n"
    "Отмечайте фильмы, которые хотите посмотреть, — раз в неделю мы выбираем из них "
    "несколько и подбираем время, когда свободно больше всего людей.\n\n"
    "Две кнопки на карточке:\n"
    "🟣 <b>Желаемое</b> — «когда-нибудь хочу», остаётся навсегда\n"
    "🟠 <b>Ближайшее</b> — «готов пойти в ближайшие две недели», весит больше "
    "и сгорает само\n\n"
    "Открывайте каталог кнопкой ниже."
)

HELP = (
    "Всё происходит в приложении — кнопка «Открыть киноклуб» под /start.\n\n"
    "Команды:\n"
    "/start — открыть каталог\n"
    "/help — эта справка"
)


def current_miniapp_url() -> str:
    """Адрес читается при каждом обращении, а не один раз на старте.

    В разработке он живёт в туннеле и меняется при каждом перезапуске. Пока
    значение сидело в замыкании, бот после смены адреса продолжал раздавать
    кнопку на мёртвый туннель, и это выглядело как «бот не работает».
    """
    get_config.cache_clear()
    return get_config().miniapp_url


def open_app_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Открыть киноклуб", web_app=WebAppInfo(url=url))]
        ]
    )


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()

    @dispatcher.message(CommandStart())
    async def start(message: Message) -> None:
        miniapp_url = current_miniapp_url()
        if not miniapp_url:
            await message.answer(
                "Приложение ещё не опубликовано: в .env не задан MINIAPP_URL. "
                "Пока открыть каталог нельзя."
            )
            return
        await message.answer(WELCOME, reply_markup=open_app_keyboard(miniapp_url))

    @dispatcher.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(HELP)

    @dispatcher.message(F.web_app_data)
    async def web_app_data(message: Message) -> None:
        # Задел под этап 4: Mini App сможет отдать боту результат отметки присутствия.
        logger.info("web_app_data от %s: %s", message.from_user.id, message.web_app_data.data)

    @dispatcher.message()
    async def fallback(message: Message) -> None:
        await message.answer(HELP)

    return dispatcher


async def apply_menu_button(bot: Bot, url: str) -> None:
    """Кнопка меню бота ведёт в Mini App.

    Ставится через API, поэтому при смене адреса туннеля BotFather править
    не нужно — достаточно, чтобы новый адрес попал в .env.
    """
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Киноклуб", web_app=WebAppInfo(url=url))
    )
    logger.info("Кнопка меню обновлена: %s", url)


async def watch_miniapp_url(bot: Bot, initial: str) -> None:
    """Следит за .env и переставляет кнопку меню, когда адрес сменился."""
    known = initial
    while True:
        await asyncio.sleep(URL_WATCH_INTERVAL_SECONDS)
        url = current_miniapp_url()
        if url and url != known:
            known = url
            try:
                await apply_menu_button(bot, url)
            except Exception:
                # Сеть до Telegram могла моргнуть — пробуем на следующем круге,
                # ронять бота из-за этого незачем.
                logger.exception("Не удалось обновить кнопку меню")


async def notification_loop(bot: Bot) -> None:
    """Отправляет накопившиеся уведомления.

    Отдельно от их создания: так падение бота не теряет уведомление — оно
    просто уйдёт следующим проходом.
    """
    while True:
        try:
            async with SessionLocal() as session:
                tz = ZoneInfo(str(await SettingsService(session).get("display_timezone")))

                def to_local(value: datetime, tz: ZoneInfo = tz) -> str:
                    return value.astimezone(tz).strftime("%d.%m в %H:%M")

                sent = await notify.deliver(session, bot, to_local)
                if sent:
                    logger.info("Отправлено уведомлений: %d", sent)
        except Exception:
            # Цикл обязан пережить любую ошибку: иначе одна неудача навсегда
            # останавливает всю рассылку.
            logger.exception("Сбой при отправке уведомлений")
        await asyncio.sleep(NOTIFY_INTERVAL_SECONDS)


async def jobs_loop() -> None:
    """Периодические задачи: напоминания, предупреждения о недоборе (§7)."""
    while True:
        try:
            async with SessionLocal() as session:
                # Порядок важен: сначала двигаем цикл, потом рассылаем — иначе
                # приглашения после автопубликации ждали бы лишние пять минут.
                await cycle.tick(session)
                await reminders.run_all(session)
        except Exception:
            logger.exception("Сбой в фоновых задачах")
        await asyncio.sleep(JOBS_INTERVAL_SECONDS)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = get_config()

    if not config.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN не задан в .env — получите токен у @BotFather (/mybots → "
            "выберите бота → API Token) и впишите его."
        )

    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dispatcher = build_dispatcher()

    me = await bot.get_me()
    url = current_miniapp_url()
    logger.info("Бот @%s запущен. Mini App: %s", me.username, url or "не задан")

    if url:
        await apply_menu_button(bot, url)
    background = [
        asyncio.create_task(watch_miniapp_url(bot, url)),
        asyncio.create_task(notification_loop(bot)),
        asyncio.create_task(jobs_loop()),
    ]

    try:
        # drop_pending_updates: перезапуск в разработке не должен разгребать очередь
        # сообщений, накопившихся, пока бот лежал.
        await dispatcher.start_polling(bot, drop_pending_updates=True)
    finally:
        for task in background:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
