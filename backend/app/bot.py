"""Telegram-бот (§12, §17).

Пускает в Mini App, знакомит с клубом при первом запуске и разгребает очередь
уведомлений. Ввод кода присутствия появится здесь же.

Запуск: ./venv/bin/python -m app.bot
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from app.config import get_config
from app.db import SessionLocal
from app.models import AuditLog, Film, User
from app.models.enums import NotificationKind
from app.services import (
    achievements,
    analytics_gate,
    cycle,
    exports,
    invites,
    notify,
    referrals,
    reminders,
    tournaments,
)
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

GATE = (
    "🔒 <b>Киноклуб пока в закрытом бета-тесте.</b>\n\n"
    "Чтобы войти, отправьте код-приглашение — его выдают администраторы клуба.\n"
    "Код из шести символов, регистр и пробелы значения не имеют."
)

WELCOME_BACK = "Код принят. Добро пожаловать в клуб!"

HELP = (
    "Всё происходит в приложении — кнопка «Открыть киноклуб» под /start.\n\n"
    "Команды:\n"
    "/start — открыть каталог\n"
    "/tour — знакомство: что умеет клуб\n"
    "/help — эта справка"
)

# --- Выгрузка данных (§14, расширение по просьбе клуба) ----------------------
#
# В /help команды нет намеренно. Она не секретная — без пароля она ничего
# не отдаёт, — но строка «/analytics — выгрузить базу клуба» в справке у всех
# подряд только подсказывает, что именно стоит попробовать подобрать. Кому
# выгрузка нужна, тот получает пароль вместе с названием команды.


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


# Знакомство при первом запуске: человек видит всё, что умеет клуб, до того,
# как откроет приложение, — иначе половина возможностей так и остаётся
# незамеченной. Листается кнопками, каждый шаг — про одну вещь.
TOUR: tuple[tuple[str, str], ...] = (
    (
        "Что здесь происходит",
        "Киноклуб выбирает фильмы не голосованием «кто громче», а по интересу "
        "всех участников: вы отмечаете, что хотите посмотреть, а раз в неделю "
        "из этих отметок собирается шорт-лист и подбирается вечер, когда "
        "свободно больше всего людей.\n\n"
        "В приложении пять вкладок: 🎞 Каталог, 🔥 Лента, 📅 Расписание, "
        "👤 Профиль и ☰ Ещё. Дальше — про каждую.",
    ),
    (
        "Две кнопки на карточке",
        "🟣 <b>Желаемое</b> — «когда-нибудь хочу». Остаётся навсегда и медленно "
        "теряет вес: свежее желание значит больше давнего.\n\n"
        "🟠 <b>Ближайшее</b> — «готов пойти в ближайшие две недели». Весит "
        "втрое больше, но через две недели само становится «Желаемым».\n\n"
        "Состояние всегда одно: вторая кнопка снимает первую. Есть ещё "
        "<b>«Смотрел»</b> — она ничему не мешает, фильм можно оставить "
        "в желаемом, чтобы сходить снова.",
    ),
    (
        "🎞 Каталог",
        "Сотня фильмов на старте и поиск по всей базе TMDB: если фильма у нас "
        "нет, он появится в момент вашей первой отметки. Порядок выбирается "
        "списком сверху, рядом — переключатель вида: строками или плиткой "
        "постеров.\n\n"
        "Не нашли фильм совсем — заявка во вкладке «Ещё», её разберут модераторы.",
    ),
    (
        "🔥 Лента",
        "Самый быстрый способ разметить каталог. Карточка на весь экран: "
        "постер, описание, рейтинги.\n\n"
        "Свайп <b>вправо</b> — «хочу посмотреть», <b>влево</b> — «не моё», "
        "больше этот фильм не покажем. Кнопка <b>«уже смотрел»</b> рядом, "
        "а если поставить звёзды — просмотр зачтётся сам, и оценка попадёт "
        "в рейтинг клуба.\n\n"
        "Полсотни карточек — минута, и шорт-лист недели собирается из живого "
        "интереса, а не из отметок пятерых самых упорных.",
    ),
    (
        "Оценки",
        "Оценить можно любой фильм и не дожидаясь показа: пять звёзд, "
        "с половинками. Нажали по своей же оценке — сняли.\n\n"
        "Из этих оценок складывается <b>рейтинг клуба</b> — он стоит на карточке "
        "отдельно от внешнего, рядом с числом оценивших. Клубу он говорит больше "
        "чужого: это вкус тех, с кем вы ходите в кино.",
    ),
    (
        "📅 Как выбирается фильм недели",
        "Среда, 20:00 — срез: считаются веса всех отметок.\n"
        "Четверг — публикуется шорт-лист, начинается голосование: вы отмечаете "
        "фильмы, которые готовы посмотреть, и вечера, когда вам удобно.\n"
        "Воскресенье — расписание готово.\n\n"
        "Всё это во вкладке <b>«Расписание»</b>: там же показы недели и кнопка "
        "«Приду». Если мест нет, вы встаёте в очередь — освободится, придёт "
        "уведомление.",
    ),
    (
        "На показе и после",
        "На месте ведущий показывает код — введите его в приложении, "
        "и присутствие зачтётся.\n\n"
        "После показа можно поставить оценку и написать отзыв — оценка попадёт "
        "в тот же рейтинг клуба.\n\n"
        "Бот сам напомнит о показе за сутки и за два часа.",
    ),
    (
        "👤 Профиль, ваши фильмы и друзья",
        "Во вкладке <b>«Профиль»</b> две двери: <b>«Мои фильмы»</b> — всё, что "
        "вы отметили и посмотрели, и <b>«Друзья»</b> — люди клуба и их лента: "
        "что отметили, что посмотрели, как оценили. Чужая оценка убеждает "
        "сходить сильнее любого рейтинга.\n\n"
        "Сам профиль тоже там: аватар, ник и распределение ваших оценок. "
        "<b>Обязательно поставьте в него четыре любимых фильма</b> — по ним вас "
        "найдут те, с кем совпадает вкус, и это первое, что видят, открыв ваш "
        "профиль. Занимает полминуты.",
    ),
    (
        "Позвать своих",
        "На карточке любого фильма есть <b>приглашение</b> — ссылка, которая "
        "ведёт друга прямо на этот фильм в боте.\n\n"
        "Голос за него никто не поставит: приглашённый видит карточку и решает "
        "сам, одним нажатием. Так вес фильма остаётся честным.\n\n"
        "Вот и всё — открывайте каталог. И не забудьте про четыре любимых "
        "фильма в профиле.",
    ),
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


async def _ensure_user(session, message: Message) -> User:
    """Аккаунт может ещё не существовать: человек написал боту, не открыв
    приложение. Заводим сразу — иначе ни приглашение засчитать, ни запомнить,
    что знакомство уже показывали."""
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
    return user


async def _user_id(session, tg_id: int) -> int | None:
    """Кто это в наших терминах. Может не найтись: /analytics бывает нужна
    и тому, кто в клубе не состоит, — на аудит это не влияет, tg_id в записи
    остаётся в любом случае."""
    return await session.scalar(sa.select(User.id).where(User.tg_id == tg_id))


def tour_text(step: int) -> str:
    title, body = TOUR[step]
    return f"<b>{title}</b>\n\n{body}\n\n<i>{step + 1} из {len(TOUR)}</i>"


def tour_keyboard(step: int, url: str) -> InlineKeyboardMarkup:
    nav: list[InlineKeyboardButton] = []
    if step > 0:
        nav.append(InlineKeyboardButton(text="‹ Назад", callback_data=f"tour:{step - 1}"))
    if step < len(TOUR) - 1:
        nav.append(InlineKeyboardButton(text="Дальше ›", callback_data=f"tour:{step + 1}"))

    rows = [nav] if nav else []
    if url:
        # Кнопка приложения на каждом шаге: знакомство можно бросить в любой
        # момент, а не дочитывать ради единственной кнопки в конце.
        rows.append(
            [InlineKeyboardButton(text="🎬 Открыть киноклуб", web_app=WebAppInfo(url=url))]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def mark_onboarded(tg_id: int) -> None:
    async with SessionLocal() as session:
        await session.execute(
            sa.update(User)
            .where(User.tg_id == tg_id, User.onboarded_at.is_(None))
            .values(onboarded_at=sa.func.now())
        )
        await session.commit()


async def needs_code(session, user: User) -> bool:
    """Остановить ли человека на коде.

    Спрашивать код у администратора нельзя: коды выдаёт он сам, и запертым
    оказался бы тот, кто должен отпирать.
    """
    return not invites.has_access(user, await invites.beta_enabled(session))


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()

    @dispatcher.message(CommandStart(deep_link=True))
    async def start_with_invite(message: Message, command: CommandObject) -> None:
        """Переход по пригласительной ссылке на конкретный фильм.

        Голос не ставится: показываем карточку и кнопку, решает человек.
        """
        parsed = referrals.parse_payload(command.args or "")
        miniapp_url = current_miniapp_url()
        if parsed is None or not miniapp_url:
            await start(message)
            return

        film_id, referrer_id = parsed
        async with SessionLocal() as session:
            invitee = await _ensure_user(session, message)
            film = await session.get(Film, film_id)
            if film is None:
                await start(message)
                return
            # Приглашение засчитываем и запертому: код он введёт следом,
            # и позвавший не должен терять его из-за порядка событий.
            await referrals.record(session, referrer_id, invitee.id, film_id)
            referrer = await session.get(User, referrer_id)
            if await needs_code(session, invitee):
                await message.answer(
                    f"Вас зовут на «{film.title_ru}» — но клуб пока в закрытом бета-тесте.\n\n"
                    f"{GATE}"
                )
                return

        who = referrer.display_name if referrer else "Кто-то из клуба"
        year = f" ({film.year})" if film.year else ""
        await message.answer(
            f"<b>{who}</b> зовёт вас на фильм\n\n"
            f"🎬 <b>{film.title_ru}</b>{year}\n\n"
            "Откройте карточку и решите сами — голос за вас никто не ставит.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Посмотреть фильм",
                            # Фильм передаём в адресе: приложение откроет сразу его.
                            web_app=WebAppInfo(url=f"{miniapp_url}?film={film_id}"),
                        )
                    ]
                ]
            ),
        )

    @dispatcher.message(CommandStart())
    async def start(message: Message) -> None:
        miniapp_url = current_miniapp_url()
        if not miniapp_url:
            await message.answer(
                "Приложение ещё не опубликовано: в .env не задан MINIAPP_URL. "
                "Пока открыть каталог нельзя."
            )
            return

        async with SessionLocal() as session:
            user = await _ensure_user(session, message)
            if await needs_code(session, user):
                await message.answer(GATE)
                return
            first_time = user.onboarded_at is None

        if first_time:
            # Первый запуск — показываем знакомство, а не короткое приветствие:
            # иначе о половине возможностей человек никогда не узнает.
            await mark_onboarded(message.from_user.id)
            await message.answer(tour_text(0), reply_markup=tour_keyboard(0, miniapp_url))
            return

        await message.answer(WELCOME, reply_markup=open_app_keyboard(miniapp_url))

    @dispatcher.message(Command("tour"))
    async def tour_command(message: Message) -> None:
        """Знакомство можно перечитать: /tour, а не «удалите чат и начните заново»."""
        async with SessionLocal() as session:
            if await needs_code(session, await _ensure_user(session, message)):
                await message.answer(GATE)
                return
        await message.answer(tour_text(0), reply_markup=tour_keyboard(0, current_miniapp_url()))

    @dispatcher.callback_query(F.data.startswith("tour:"))
    async def tour_step(callback: CallbackQuery) -> None:
        _, _, raw = callback.data.partition(":")
        step = max(0, min(int(raw) if raw.isdigit() else 0, len(TOUR) - 1))
        try:
            await callback.message.edit_text(
                tour_text(step), reply_markup=tour_keyboard(step, current_miniapp_url())
            )
        except TelegramBadRequest:
            # Двойное нажатие на ту же кнопку: текст не изменился, Telegram
            # считает это ошибкой. Для человека ничего не произошло.
            pass
        await callback.answer()

    @dispatcher.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(HELP)

    @dispatcher.message(Command("analytics"))
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

    @dispatcher.message(AnalyticsGate.waiting_password)
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
                        actor_id=await _user_id(session, tg_id),
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

    @dispatcher.callback_query(F.data.startswith("dl:"))
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
                        actor_id=await _user_id(session, tg_id),
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

    @dispatcher.message(F.web_app_data)
    async def web_app_data(message: Message) -> None:
        # Задел под этап 4: Mini App сможет отдать боту результат отметки присутствия.
        logger.info("web_app_data от %s: %s", message.from_user.id, message.web_app_data.data)

    @dispatcher.message()
    async def fallback(message: Message) -> None:
        """Любое сообщение от человека без доступа — попытка ввести код.

        Отдельной команды нет намеренно: человек, которого встретили запертой
        дверью, пишет код сразу, а не ищет, каким глаголом его назвать.
        """
        async with SessionLocal() as session:
            user = await _ensure_user(session, message)
            if not await needs_code(session, user):
                await message.answer(HELP)
                return

            try:
                await invites.redeem(session, user, message.text or "")
            except invites.InviteError as exc:
                await message.answer(f"{exc}.\n\n{GATE}")
                return

            # Код принят — сразу знакомство, а не «нажмите /start ещё раз».
            user.onboarded_at = sa.func.now()
            await session.commit()

        url = current_miniapp_url()
        await message.answer(WELCOME_BACK)
        await message.answer(tour_text(0), reply_markup=tour_keyboard(0, url))

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


def _notify_keyboard(kind: NotificationKind, payload: dict):
    """Кнопка приложения там, где сообщение зовёт зайти."""
    url = current_miniapp_url()
    if kind == NotificationKind.BETA_OPENED and url:
        return open_app_keyboard(url)
    return None


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

                sent = await notify.deliver(session, bot, to_local, keyboard=_notify_keyboard)
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
                await tournaments.tick(session)
                await achievements.award(session)
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
