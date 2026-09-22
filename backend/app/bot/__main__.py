"""Запуск бота: ./venv/bin/python -m app.bot"""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import MenuButtonWebApp, WebAppInfo

from app.bot import common, export, loops, onboarding, votes
from app.config import get_config

logger = logging.getLogger("app.bot")

# Как часто перечитывать .env в поисках нового адреса туннеля.
URL_WATCH_INTERVAL_SECONDS = 5


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    # Порядок — это приоритет: ответ «на всё остальное» обязан стоять последним,
    # иначе он перехватил бы и команды, и ввод пароля.
    dispatcher.include_routers(
        onboarding.router, votes.router, export.router, onboarding.fallback_router
    )
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
        url = common.current_miniapp_url()
        if url and url != known:
            known = url
            try:
                await apply_menu_button(bot, url)
            except Exception:
                # Сеть до Telegram могла моргнуть — пробуем на следующем круге,
                # ронять бота из-за этого незачем.
                logger.exception("Не удалось обновить кнопку меню")


async def main() -> int:
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
    url = common.current_miniapp_url()
    logger.info("Бот @%s запущен. Mini App: %s", me.username, url or "не задан")

    if url:
        await apply_menu_button(bot, url)

    background = [
        asyncio.create_task(watch_miniapp_url(bot, url)),
        asyncio.create_task(loops.notification_loop(bot)),
        asyncio.create_task(loops.jobs_loop()),
    ]
    pulses = [loops.NOTIFY, loops.JOBS]
    # Копии снимаются только там, где им отведено место, — в бою. На машине
    # разработчика дамп учебной базы никому не нужен.
    if config.backup_dir:
        background.append(asyncio.create_task(loops.backup_loop(bot, Path(config.backup_dir))))
        pulses.append(loops.BACKUP)
    guard = asyncio.create_task(loops.watchdog(bot, tuple(pulses)))

    # drop_pending_updates: перезапуск в разработке не должен разгребать очередь
    # сообщений, накопившихся, пока бот лежал.
    polling = asyncio.create_task(dispatcher.start_polling(bot, drop_pending_updates=True))
    try:
        await asyncio.wait({polling, guard}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if not polling.done():
            try:
                await dispatcher.stop_polling()
            except RuntimeError:
                # Опрос ещё не успел стартовать — останавливать нечего.
                pass
        for task in (*background, guard, polling):
            task.cancel()
        await bot.session.close()

    if polling.done() and not polling.cancelled() and polling.exception() is not None:
        raise polling.exception()
    # Сторож сработал — выходим с ошибкой, и Docker поднимает процесс заново.
    return 1 if guard.done() and not guard.cancelled() else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
