"""Доставка уведомлений в Telegram (§7, §17).

Уведомления пишутся в таблицу теми, кто их порождает, а отправляются отдельно.
Так у отправки появляется одно место, где живут повторные попытки, и запись
переживает падение бота: неотправленное просто уйдёт следующим проходом.

Идемпотентность держится на `dedup_key`: повторный запуск фоновой задачи
не создаёт вторую запись, а значит и второго сообщения.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Film, Notification, Screening, Slot, User
from app.models.enums import NotificationKind

logger = logging.getLogger(__name__)

# Сколько сообщений отправляем за один проход. Telegram допускает ~30 сообщений
# в секунду; проход раз в несколько секунд с таким размером в лимит укладывается.
BATCH = 25

# Пауза между сообщениями. Лимит общий на бота, и пачка приглашений, отправленная
# залпом, упирается в него целиком — а каждое отбитое сообщение стоит нам ещё
# одного круга ожидания.
SEND_INTERVAL_SECONDS = 0.04

# Сколько раз пробуем, прежде чем признать уведомление недоставленным, и через
# сколько секунд после каждой неудачи. Минута — почти всегда достаточно (сеть
# моргнула), час — последний шанс на случай долгой недоступности Telegram.
RETRY_DELAYS_SECONDS = (60, 300, 900, 3600)
MAX_ATTEMPTS = len(RETRY_DELAYS_SECONDS) + 1

# Разблокировать бота можно и молча, без /start, — тогда пометка сама себя
# не снимет. Раз в месяц пробуем снова: один отказ в месяц дешевле, чем
# навсегда потерянный человек.
RECHECK_BLOCKED_AFTER = timedelta(days=30)

# Ошибки, после которых повторять бессмысленно: человек заблокировал бота,
# удалил аккаунт или чата просто нет. Опознаём по имени класса и тексту, а не
# по типу: aiogram — деталь бота, и сервис о нём знать не должен.
PERMANENT_ERROR_NAMES = frozenset(
    {"TelegramForbiddenError", "TelegramUnauthorizedError", "TelegramNotFound"}
)
PERMANENT_ERROR_MARKERS = (
    "blocked",
    "chat not found",
    "user is deactivated",
    "bot was kicked",
)


async def queue(
    session: AsyncSession,
    user_id: int,
    kind: NotificationKind,
    dedup_key: str | None,
    payload: dict | None = None,
) -> bool:
    """Ставит уведомление в очередь, пропуская уже поставленное.

    dedup_key уникален, поэтому обычный session.add() на повторе ронял бы
    IntegrityError и вместе с ним весь пакет — а повтор здесь ожидаем:
    фоновые задачи выполняются много раз и обязаны быть идемпотентными (§17).
    Возвращает True, если запись действительно создана.
    """
    stmt = (
        insert(Notification)
        .values(user_id=user_id, kind=kind, dedup_key=dedup_key, payload=payload or {})
        .on_conflict_do_nothing(index_elements=[Notification.dedup_key])
        .returning(Notification.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


def _film_line(film: Film | None) -> str:
    if film is None:
        return "фильм"
    year = f" ({film.year})" if film.year else ""
    # Сообщения уходят с parse_mode=HTML: «&» или «<» в названии из TMDB
    # иначе роняли бы отправку — Telegram отвергает разметку целиком.
    return f"<b>{escape(film.title_ru)}</b>{year}"


def _when(slot: Slot | None, tz_convert: Callable[[object], str]) -> str:
    return tz_convert(slot.starts_at) if slot else "—"


async def _context(
    session: AsyncSession, notification: Notification
) -> tuple[Film | None, Slot | None]:
    screening_id = (notification.payload or {}).get("screening_id")
    if not screening_id:
        return None, None
    screening = await session.get(Screening, screening_id)
    if screening is None:
        return None, None
    return await session.get(Film, screening.film_id), await session.get(Slot, screening.slot_id)


@dataclass(frozen=True, slots=True)
class Message:
    """Всё, из чего складывается текст одного уведомления."""

    film_line: str
    when: str
    payload: dict

    def text(self, key: str, default: str = "") -> str:
        """Поле из payload, готовое к вставке в HTML.

        Всё, что написал человек (причина отмены, комментарий к заявке,
        название турнира), экранируется здесь, а не в каждом шаблоне: один
        забытый escape — и сообщение с «<3» в тексте не уходило никому.
        """
        value = self.payload.get(key)
        return escape(str(value)) if value not in (None, "") else default


def _registration_link(m: Message) -> str:
    # В очереди ссылка тоже нужна: место может освободиться в последний
    # час, и регистрироваться тогда будет некогда.
    place = (
        "Вы в листе ожидания — место может освободиться, и регистрация понадобится сразу."
        if m.payload.get("waitlist")
        else "Вы записаны."
    )
    return (
        f"📝 <b>Регистрация на показ</b>\n\n{m.film_line}\n{m.when}\n\n"
        f"{place}\nОсталось отметиться у вуза — это отдельный от клуба учёт:\n"
        f"{m.text('url')}"
    )


def _achievement_earned(m: Message) -> str:
    emoji = m.payload.get("emoji", "🏅")
    title = m.text("title", "Ачивка")
    tier = m.text("tier")
    hint = m.text("hint")

    if m.payload.get("secret"):
        # Про секретную важно сказать, что она секретная: человек её не искал
        # и не знал о ней, и без этого награда выглядит обычной ступенью,
        # которую он и так бы взял.
        return (
            f"🕵️ <b>Секретное достижение открыто!</b>\n\n"
            f"{emoji} <b>{title}</b>\n{hint}\n"
            f"{tier} — и её никто не подсказывал.\n\n"
            "Все трофеи — в профиле."
        )
    if m.payload.get("custom"):
        # Именную придумали лично для него — «следующей ступени» у неё нет
        # и быть не может.
        return (
            f"{emoji} <b>{title}</b>\n"
            f"{tier} ачивка от клуба{f' — {hint}' if hint else ''}\n\n"
            "Её выдали вам лично. Все трофеи — в профиле."
        )

    # Что дальше — обязательная часть: без неё поздравление сообщает только
    # о конце, а у ачивки со ступенями всегда есть продолжение. Название
    # следующей не раскрываем — только условие: в профиле оно тоже скрыто
    # до получения, и портить сюрприз здесь незачем.
    #
    # Ключа нет вовсе — запись из очереди старше этого поля: про следующую
    # ступень она ничего не знает, и выдумывать «выше некуда» нельзя.
    ahead = ""
    if "next_hint" in m.payload:
        following = m.text("next_hint")
        ahead = (
            f"\n\nДальше — {following[:1].lower()}{following[1:]}."
            if following
            else "\n\nЭто верхняя ступень — выше некуда."
        )
    earned = f"{tier} ачивка — {hint}" if hint else f"{tier} ачивка"
    return f"{emoji} <b>{title}</b>\n{earned}{ahead}\n\nВсе трофеи — в профиле."


def _tournament_started(m: Message) -> str:
    return (
        f"🏆 <b>{m.text('title', 'Турнир')}</b>\n\n"
        f"Начался турнир — идёт {m.text('round', 'первый этап')}. "
        "Выберите в каждой паре того, кто должен пройти дальше.\n"
        "Новый этап каждый день, голосовать можно до его конца."
    )


def _tournament_round_opened(m: Message) -> str:
    return (
        f"🏆 <b>{m.text('title', 'Турнир')}</b>\n\n"
        f"Новый этап: {m.text('round', 'следующий круг')}. "
        "Пары обновились — загляните и проголосуйте."
    )


def _tournament_finished(m: Message) -> str:
    return (
        f"🏆 <b>{m.text('title', 'Турнир')}</b> — победитель!\n\n"
        f"🥇 {m.text('winner', '—')}\n\n"
        "Спасибо всем, кто голосовал."
    )


def _shortlist_published(m: Message) -> str:
    # Фильм приходит словарём {id, title}: у каждого своя кнопка под
    # сообщением. Старые записи в очереди хранят голое название — шаблон
    # переживает и их.
    films = m.payload.get("films") or []
    listed = "\n".join(
        f"• {escape(str(film.get('title') if isinstance(film, dict) else film))}"
        for film in films
    )
    # Язык показа влияет на то, пойдёт ли человек, — значит, знать о нём
    # надо до голоса, а не из расписания.
    language = (
        "\n\n🇬🇧 <b>Показ пройдёт на английском</b> — оригинал без дубляжа."
        if m.payload.get("in_english")
        else ""
    )
    # Напоминание — то же сообщение, но вторым заходом: в первый раз оно
    # могло уйти без кнопок или просто утонуть в переписке. Повторять
    # «голосование открыто» тому, кто это уже читал, незачем.
    head = (
        "🗳 <b>Голосование идёт</b> — отметить фильмы можно прямо здесь."
        if m.payload.get("reminder")
        else "🗳 <b>Голосование открыто!</b>"
    )
    return (
        f"{head}\n\nФильмы недели:\n{listed}{language}\n\n"
        "Отметьте кнопками, на какие фильмы пошли бы, — а вечера, "
        "когда вы свободны, выберите в приложении."
    )


def _schedule_published(m: Message) -> str:
    return (
        f"🎬 Расписание готово!\n\n{m.film_line}\n{m.when}\n\n"
        "Вы голосовали за этот фильм — отметьте в приложении, придёте ли."
    )


def _waitlist_promoted(m: Message) -> str:
    return (
        f"✅ Место освободилось!\n\n{m.film_line}\n{m.when}\n\n"
        "Вы были в очереди, теперь вы в списке. Ждём вас."
    )


def _screening_cancelled(m: Message) -> str:
    reason = m.text("reason", "без указания причины")
    return f"❌ Показ отменён\n\n{m.film_line}\n{m.when}\n\nПричина: {reason}"


def _screening_changed(m: Message) -> str:
    if m.payload.get("time_changed"):
        if m.payload.get("kept"):
            # Записи оставили: просить отметиться заново там, где человек уже
            # отметился, значит потерять половину зала на ровном месте.
            return (
                f"🔄 Показ перенесён\n\n{m.film_line}\nНовое время: {m.when}\n\n"
                "Вы записаны — если не сможете, отмените в приложении."
            )
        return (
            f"🔄 Показ перенесён\n\n{m.film_line}\nНовое время: {m.when}\n\n"
            "Подтверждения сброшены — отметьтесь заново, если придёте."
        )
    if m.payload.get("film_changed"):
        # Человек шёл на конкретное кино: «вместо чего» ему важнее, чем «что
        # теперь». Без прежнего названия сообщение выглядит как непонятное
        # «изменение» без содержания.
        was = m.text("was_film")
        instead = f"\nВместо: {was}" if was else ""
        place = (
            "\n\nВы записаны — если новый фильм не ваш, отмените запись в приложении."
            if m.payload.get("kept")
            else ""
        )
        return f"🔄 Фильм заменён\n\n{m.film_line}\n{m.when}{instead}{place}"
    if m.payload.get("revealed"):
        # Ради этого «секретный показ» и заводят: время объявили заранее,
        # название — сейчас. Для записавшихся это не «изменение», а тот самый
        # анонс, которого они ждали.
        return f"🎬 Фильм объявлен!\n\n{m.film_line}\n{m.when}\n\nВы записаны — место за вами."
    return f"🔄 Изменение\n\n{m.film_line}\n{m.when}"


def _reminder_24h(m: Message) -> str:
    return (
        f"⏰ Завтра показ\n\n{m.film_line}\n{m.when}\n\n"
        "Если планы изменились — отмените заранее."
    )


def _reminder_2h(m: Message) -> str:
    return f"⏰ Через два часа\n\n{m.film_line}\n{m.when}\n\nДо встречи!"


def _feedback_reminder(m: Message) -> str:
    # Про отчётность говорим прямо: просьба «оцените честно» без объяснения,
    # зачем это клубу, читается как вежливая формальность, и в ответ приходят
    # вежливые пятёрки.
    return (
        f"⭐️ Как вам {m.film_line}?\n\n"
        "Клуб отчитывается перед вузом — и отчёт складывается из ваших "
        "ответов, а не из наших ощущений. Четыре вопроса, полминуты. "
        "Отвечайте честно: заниженная оценка нам полезнее вежливой."
    )


def _admin_low_attendance(m: Message) -> str:
    confirmed = m.payload.get("confirmed", 0)
    needed = m.payload.get("min_attendance", 0)
    return (
        f"⚠️ Мало подтверждений\n\n{m.film_line}\n{m.when}\n\n"
        f"Придут {confirmed}, кворум {needed}. Решение о проведении за вами."
    )


def _role_granted(m: Message) -> str:
    # Что именно человек теперь умеет, решает вызывающий: список прав живёт
    # в roles.py, а не размазывается по шаблонам сообщений.
    title = m.text("role_title", "новая роль")
    if m.payload.get("demoted"):
        return f"Ваша роль в клубе изменена: <b>{title}</b>."
    parts = [
        f"🔑 Вам выдали роль: <b>{title}</b>",
        m.text("abilities"),
        "Откройте приложение — вкладка «Клуб» уже на месте.",
    ]
    return "\n\n".join(part for part in parts if part)


def _admin_autopilot_soon(m: Message) -> str:
    what = m.text("what", "решит сам")
    minutes = int(m.payload.get("minutes") or 60)
    week = m.text("week_start")
    # Выключенный автопилот — новость важнее включённого: тогда не
    # произойдёт вообще ничего, и неделя останется без кино.
    if m.payload.get("enabled"):
        return (
            f"⏳ <b>Через {minutes} мин автопилот {what}</b>\n\n"
            f"Неделя показов с {week}.\n"
            "Если хотите решить сами — сейчас самое время: после "
            "автопилота список уходит дальше по циклу."
        )
    return (
        f"⏳ <b>Через {minutes} мин срок, к которому автопилот {what}</b>\n\n"
        f"Неделя показов с {week}.\n"
        "Автопилот на этом этапе выключен — если не сделать этого "
        "руками, не произойдёт ничего."
    )


def _admin_broadcast(m: Message) -> str | None:
    message = m.text("text")
    if not message:
        return None
    # Подпись обязательна: сообщение приходит от бота, и человек должен
    # понимать, что это клуб, а не система напоминаний ошиблась.
    return f"📣 <b>Сообщение от клуба</b>\n\n{message}"


def _film_request_resolved(m: Message) -> str:
    if m.payload.get("approved"):
        return "✅ Ваш фильм добавлен в каталог — можно отмечать."
    return f"Заявку на фильм отклонили.\n\n{m.text('comment', 'без комментария')}"


# Вид уведомления → шаблон. Вида нет в таблице — текста для него ещё нет,
# и доставка пометит запись, а не будет крутить её в очереди вечно.
TEMPLATES: dict[NotificationKind, Callable[[Message], str | None]] = {
    NotificationKind.REGISTRATION_LINK: _registration_link,
    NotificationKind.ACHIEVEMENT_EARNED: _achievement_earned,
    NotificationKind.TOURNAMENT_STARTED: _tournament_started,
    NotificationKind.TOURNAMENT_ROUND_OPENED: _tournament_round_opened,
    NotificationKind.TOURNAMENT_FINISHED: _tournament_finished,
    NotificationKind.SHORTLIST_PUBLISHED: _shortlist_published,
    NotificationKind.SCHEDULE_PUBLISHED: _schedule_published,
    NotificationKind.WAITLIST_PROMOTED: _waitlist_promoted,
    NotificationKind.SCREENING_CANCELLED: _screening_cancelled,
    NotificationKind.SCREENING_CHANGED: _screening_changed,
    NotificationKind.REMINDER_24H: _reminder_24h,
    NotificationKind.REMINDER_2H: _reminder_2h,
    NotificationKind.FEEDBACK_REMINDER: _feedback_reminder,
    NotificationKind.ADMIN_LOW_ATTENDANCE: _admin_low_attendance,
    NotificationKind.ROLE_GRANTED: _role_granted,
    NotificationKind.ADMIN_AUTOPILOT_SOON: _admin_autopilot_soon,
    NotificationKind.ADMIN_BROADCAST: _admin_broadcast,
    NotificationKind.FILM_REQUEST_RESOLVED: _film_request_resolved,
}


def render(kind: NotificationKind, film: Film | None, when: str, payload: dict) -> str | None:
    """Текст сообщения. None — значит для этого вида текста пока нет."""
    template = TEMPLATES.get(kind)
    if template is None:
        return None
    return template(Message(film_line=_film_line(film), when=when, payload=payload or {}))


async def pending(session: AsyncSession, limit: int = BATCH) -> list[Notification]:
    """Что готово к отправке прямо сейчас.

    `failed_reason` означает «больше не пробуем», а отложенная попытка ждёт
    своего времени в `next_attempt_at` — иначе очередь крутила бы одно и то же
    сообщение каждые пять секунд.
    """
    rows = await session.execute(
        sa.select(Notification)
        .where(
            Notification.sent_at.is_(None),
            Notification.failed_reason.is_(None),
            sa.or_(
                Notification.next_attempt_at.is_(None),
                Notification.next_attempt_at <= sa.func.now(),
            ),
        )
        .order_by(Notification.created_at)
        .limit(limit)
    )
    return list(rows.scalars())


def _is_permanent(exc: Exception) -> bool:
    text = str(exc).lower()
    return type(exc).__name__ in PERMANENT_ERROR_NAMES or any(
        marker in text for marker in PERMANENT_ERROR_MARKERS
    )


def _retry_delay(exc: Exception, attempts: int) -> float:
    """Через сколько секунд пробовать снова.

    Telegram на 429 сам говорит, сколько ждать (`retry_after` у исключения
    aiogram) — его слово точнее нашей лесенки.
    """
    asked = getattr(exc, "retry_after", None)
    if isinstance(asked, int | float) and asked > 0:
        return float(asked)
    return float(RETRY_DELAYS_SECONDS[min(attempts, len(RETRY_DELAYS_SECONDS)) - 1])


def _postpone(notification: Notification, exc: Exception) -> None:
    """Временная ошибка: считаем попытку и откладываем следующую."""
    notification.attempts += 1
    reason = f"{type(exc).__name__}: {exc}"[:500]
    if notification.attempts >= MAX_ATTEMPTS:
        notification.failed_reason = reason
        logger.warning("Уведомление %s недоставлено: %s", notification.id, exc)
        return
    delay = _retry_delay(exc, notification.attempts)
    notification.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
    logger.info(
        "Уведомление %s отложено на %.0f с (попытка %s): %s",
        notification.id,
        delay,
        notification.attempts,
        exc,
    )


async def deliver(
    session: AsyncSession,
    bot,
    tz_convert: Callable[[object], str],
    keyboard: Callable[[NotificationKind, dict], object | None] | None = None,
) -> int:
    """Отправляет накопившиеся уведомления. Возвращает число отправленных.

    `keyboard` даёт вызывающему приложить к сообщению кнопку — типы клавиатур
    живут в aiogram, а этот модуль о мессенджере знать не обязан.
    """
    sent = 0
    for index, notification in enumerate(await pending(session)):
        user = await session.get(User, notification.user_id)
        if user is None or user.tg_id is None:
            notification.failed_reason = "нет привязки Telegram"
            await session.commit()
            continue
        if (
            user.bot_blocked_at is not None
            and user.bot_blocked_at > datetime.now(UTC) - RECHECK_BLOCKED_AFTER
        ):
            # Заведомый отказ — не тратим на него ни запрос, ни паузу в очереди.
            notification.failed_reason = "заблокировал бота"
            await session.commit()
            continue

        film, slot = await _context(session, notification)
        text = render(
            notification.kind, film, _when(slot, tz_convert), notification.payload or {}
        )
        if text is None:
            # Вид уведомления есть, а текста для него ещё нет. Помечаем, чтобы
            # запись не крутилась в очереди вечно.
            notification.failed_reason = "нет шаблона"
            await session.commit()
            continue

        if index:
            await asyncio.sleep(SEND_INTERVAL_SECONDS)

        try:
            await bot.send_message(
                user.tg_id,
                text,
                reply_markup=(
                    keyboard(notification.kind, notification.payload or {}) if keyboard else None
                ),
            )
            notification.sent_at = sa.func.now()
            sent += 1
        except Exception as exc:  # noqa: BLE001 — причина уходит в поле и в лог
            if _is_permanent(exc):
                # Заблокировал бота, удалил аккаунт — повторять нечего.
                notification.failed_reason = f"{type(exc).__name__}: {exc}"[:500]
                # Время — питоновское, не now() базы: в этой же пачке человеку
                # может идти ещё одно сообщение, и проверка выше сравнивает его.
                user.bot_blocked_at = datetime.now(UTC)
                logger.warning("Не доставлено пользователю %s: %s", user.id, exc)
            else:
                # Сеть моргнула, Telegram ответил 429 или 500 — это про момент,
                # а не про адресата: пробуем снова позже.
                _postpone(notification, exc)

        # Коммит после каждого сообщения, а не раз на пачку: падение процесса
        # между отправкой и коммитом иначе разослало бы всю пачку повторно.
        await session.commit()

    return sent
