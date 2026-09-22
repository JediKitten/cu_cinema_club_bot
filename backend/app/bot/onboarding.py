"""Первый контакт с ботом: /start, знакомство, справка, приглашения на фильм."""

from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import common
from app.db import SessionLocal
from app.models import Film, User
from app.services import referrals

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
    "/tour — знакомство: что умеет клуб\n"
    "/help — эта справка"
)


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
        "В приложении четыре вкладки: 🎞 Каталог, 🔥 Лента, 📅 Расписание "
        "и 👤 Профиль. Дальше — про каждую.",
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
        "Не нашли фильм совсем — оставьте заявку: профиль → ☰ в углу. "
        "Её разберут модераторы.",
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
        rows.append([common.app_button("🎬 Открыть киноклуб", url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


router = Router(name="onboarding")


@router.message(CommandStart(deep_link=True))
async def start_with_invite(message: Message, command: CommandObject) -> None:
    """Переход по пригласительной ссылке на конкретный фильм.

    Голос не ставится: показываем карточку и кнопку, решает человек.
    """
    parsed = referrals.parse_payload(command.args or "")
    miniapp_url = common.current_miniapp_url()
    if parsed is None or not miniapp_url:
        await start(message)
        return

    film_id, referrer_id = parsed
    async with SessionLocal() as session:
        invitee = await common.ensure_user(session, message)
        film = await session.get(Film, film_id)
        if film is None:
            await start(message)
            return
        await referrals.record(session, referrer_id, invitee.id, film_id)
        referrer = await session.get(User, referrer_id)

    # Имя берётся из Telegram как есть, а бот пишет в HTML: «<3» в имени
    # делало разметку невалидной, и приглашённый не получал ответа вовсе.
    who = escape(referrer.display_name) if referrer else "Кто-то из клуба"
    year = f" ({film.year})" if film.year else ""
    await message.answer(
        f"<b>{who}</b> зовёт вас на фильм\n\n"
        f"🎬 <b>{escape(film.title_ru)}</b>{year}\n\n"
        "Откройте карточку и решите сами — голос за вас никто не ставит.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                # Фильм передаём в адресе: приложение откроет сразу его.
                [common.app_button("Посмотреть фильм", f"{miniapp_url}?film={film_id}")]
            ]
        ),
    )


@router.message(CommandStart())
async def start(message: Message) -> None:
    miniapp_url = common.current_miniapp_url()
    if not miniapp_url:
        await message.answer(
            "Приложение ещё не опубликовано: в .env не задан MINIAPP_URL. "
            "Пока открыть каталог нельзя."
        )
        return

    async with SessionLocal() as session:
        user = await common.ensure_user(session, message)
        first_time = user.onboarded_at is None

    if first_time:
        # Первый запуск — показываем знакомство, а не короткое приветствие:
        # иначе о половине возможностей человек никогда не узнает.
        await common.mark_onboarded(message.from_user.id)
        await message.answer(tour_text(0), reply_markup=tour_keyboard(0, miniapp_url))
        return

    await message.answer(WELCOME, reply_markup=common.open_app_keyboard(miniapp_url))


@router.message(Command("tour"))
async def tour_command(message: Message) -> None:
    """Знакомство можно перечитать: /tour, а не «удалите чат и начните заново»."""
    async with SessionLocal() as session:
        await common.ensure_user(session, message)
    await message.answer(
        tour_text(0), reply_markup=tour_keyboard(0, common.current_miniapp_url())
    )


@router.callback_query(F.data.startswith("tour:"))
async def tour_step(callback: CallbackQuery) -> None:
    _, _, raw = callback.data.partition(":")
    step = max(0, min(int(raw) if raw.isdigit() else 0, len(TOUR) - 1))
    try:
        await callback.message.edit_text(
            tour_text(step), reply_markup=tour_keyboard(step, common.current_miniapp_url())
        )
    except TelegramBadRequest:
        # Двойное нажатие на ту же кнопку: текст не изменился, Telegram
        # считает это ошибкой. Для человека ничего не произошло.
        pass
    await callback.answer()


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP)


# Всё, что не поймали остальные роутеры. Отдельным роутером, чтобы его можно
# было подключить последним: обработчик без фильтров, стоящий раньше,
# проглотил бы и /analytics, и ввод пароля.
fallback_router = Router(name="fallback")


@fallback_router.message()
async def fallback(message: Message) -> None:
    """Всё, что не команда: человек написал боту и ждёт ответа."""
    async with SessionLocal() as session:
        await common.ensure_user(session, message)
    await message.answer(HELP)
