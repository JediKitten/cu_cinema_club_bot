"""Telegram-бот (§12, §17).

Пока делает одно: пускает в Mini App и объясняет, что это такое. Уведомления
этапов 3–4 и ввод кода присутствия появятся здесь же.

Запуск: ./venv/bin/python -m app.bot
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.config import get_config

logger = logging.getLogger(__name__)

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


def open_app_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Открыть киноклуб", web_app=WebAppInfo(url=url))]
        ]
    )


def build_dispatcher(miniapp_url: str) -> Dispatcher:
    dispatcher = Dispatcher()

    @dispatcher.message(CommandStart())
    async def start(message: Message) -> None:
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
    dispatcher = build_dispatcher(config.miniapp_url)

    me = await bot.get_me()
    logger.info("Бот @%s запущен. Mini App: %s", me.username, config.miniapp_url or "не задан")

    # drop_pending_updates: перезапуск в разработке не должен разгребать очередь
    # сообщений, накопившихся, пока бот лежал.
    await dispatcher.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
