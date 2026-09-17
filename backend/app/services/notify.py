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
    return f"<b>{film.title_ru}</b>{year}"


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


def render(kind: NotificationKind, film: Film | None, when: str, payload: dict) -> str | None:
    """Текст сообщения. None — значит для этого вида текста пока нет."""
    film_line = _film_line(film)

    match kind:
        case NotificationKind.REGISTRATION_LINK:
            url = escape(str(payload.get("url", "")))
            # В очереди ссылка тоже нужна: место может освободиться в последний
            # час, и регистрироваться тогда будет некогда.
            place = (
                "Вы в листе ожидания — место может освободиться, "
                "и регистрация понадобится сразу."
                if payload.get("waitlist")
                else "Вы записаны."
            )
            return (
                f"📝 <b>Регистрация на показ</b>\n\n{film_line}\n{when}\n\n"
                f"{place}\nОсталось отметиться у вуза — это отдельный от клуба учёт:\n"
                f"{url}"
            )
        case NotificationKind.ACHIEVEMENT_EARNED:
            emoji = payload.get("emoji", "🏅")
            title = escape(str(payload.get("title", "Ачивка")))
            tier = escape(str(payload.get("tier", "")))
            hint = escape(str(payload.get("hint", "")))

            if payload.get("secret"):
                # Про секретную важно сказать, что она секретная: человек её
                # не искал и не знал о ней, и без этого награда выглядит
                # обычной ступенью, которую он и так бы взял.
                return (
                    f"🕵️ <b>Секретное достижение открыто!</b>\n\n"
                    f"{emoji} <b>{title}</b>\n{hint}\n"
                    f"{tier} — и её никто не подсказывал.\n\n"
                    "Все трофеи — в профиле."
                )
            if payload.get("custom"):
                # Именную придумали лично для него — «следующей ступени» у неё
                # нет и быть не может.
                return (
                    f"{emoji} <b>{title}</b>\n"
                    f"{tier} ачивка от клуба{f' — {hint}' if hint else ''}\n\n"
                    "Её выдали вам лично. Все трофеи — в профиле."
                )

            # Что дальше — обязательная часть: без неё поздравление сообщает
            # только о конце, а у ачивки со ступенями всегда есть продолжение.
            nxt = payload.get("next_title")
            ahead = (
                f"\n\nДальше — <b>{escape(str(nxt))}</b>: "
                f"{escape(str(payload.get('next_hint', '')))}"
                if nxt
                else "\n\nЭто верхняя ступень — выше некуда."
            )
            return (
                f"{emoji} <b>{title}</b>\n{tier} ачивка — {hint}"
                f"{ahead}\n\nВсе трофеи — в профиле."
            )
        case NotificationKind.TOURNAMENT_STARTED:
            return (
                f"🏆 <b>{escape(str(payload.get('title', 'Турнир')))}</b>\n\n"
                f"Начался турнир — идёт {payload.get('round', 'первый этап')}. "
                "Выберите в каждой паре того, кто должен пройти дальше.\n"
                "Новый этап каждый день, голосовать можно до его конца."
            )
        case NotificationKind.TOURNAMENT_ROUND_OPENED:
            return (
                f"🏆 <b>{escape(str(payload.get('title', 'Турнир')))}</b>\n\n"
                f"Новый этап: {payload.get('round', 'следующий круг')}. "
                "Пары обновились — загляните и проголосуйте."
            )
        case NotificationKind.TOURNAMENT_FINISHED:
            return (
                f"🏆 <b>{escape(str(payload.get('title', 'Турнир')))}</b> — победитель!\n\n"
                f"🥇 {escape(str(payload.get('winner', '—')))}\n\n"
                "Спасибо всем, кто голосовал."
            )
        case NotificationKind.SHORTLIST_PUBLISHED:
            # Фильм приходит словарём {id, title}: у каждого своя кнопка под
            # сообщением. Старые записи в очереди хранят голое название —
            # шаблон переживает и их.
            films = payload.get("films") or []
            listed = "\n".join(
                f"• {escape(str(film.get('title') if isinstance(film, dict) else film))}"
                for film in films
            )
            # Язык показа влияет на то, пойдёт ли человек, — значит, знать
            # о нём надо до голоса, а не из расписания.
            language = (
                "\n\n🇬🇧 <b>Показ пройдёт на английском</b> — оригинал без дубляжа."
                if payload.get("in_english")
                else ""
            )
            return (
                "🗳 <b>Голосование открыто!</b>\n\n"
                "Фильмы недели:\n"
                f"{listed}"
                f"{language}\n\n"
                "Отметьте кнопками, на какие фильмы пошли бы, — а вечера, "
                "когда вы свободны, выберите в приложении."
            )
        case NotificationKind.SCHEDULE_PUBLISHED:
            return (
                f"🎬 Расписание готово!\n\n{film_line}\n{when}\n\n"
                "Вы голосовали за этот фильм — отметьте в приложении, придёте ли."
            )
        case NotificationKind.WAITLIST_PROMOTED:
            return (
                f"✅ Место освободилось!\n\n{film_line}\n{when}\n\n"
                "Вы были в очереди, теперь вы в списке. Ждём вас."
            )
        case NotificationKind.SCREENING_CANCELLED:
            reason = payload.get("reason", "без указания причины")
            return f"❌ Показ отменён\n\n{film_line}\n{when}\n\nПричина: {reason}"
        case NotificationKind.SCREENING_CHANGED:
            if payload.get("time_changed"):
                if payload.get("kept"):
                    # Записи оставили: просить отметиться заново там, где человек
                    # уже отметился, значит потерять половину зала на ровном месте.
                    return (
                        f"🔄 Показ перенесён\n\n{film_line}\nНовое время: {when}\n\n"
                        "Вы записаны — если не сможете, отмените в приложении."
                    )
                return (
                    f"🔄 Показ перенесён\n\n{film_line}\nНовое время: {when}\n\n"
                    "Подтверждения сброшены — отметьтесь заново, если придёте."
                )
            if payload.get("revealed"):
                # Ради этого «секретный показ» и заводят: время объявили заранее,
                # название — сейчас. Для записавшихся это не «изменение», а тот
                # самый анонс, которого они ждали.
                return (
                    f"🎬 Фильм объявлен!\n\n{film_line}\n{when}\n\n"
                    "Вы записаны — место за вами."
                )
            return f"🔄 Изменение\n\n{film_line}\n{when}"
        case NotificationKind.REMINDER_24H:
            return (
                f"⏰ Завтра показ\n\n{film_line}\n{when}\n\n"
                "Если планы изменились — отмените заранее."
            )
        case NotificationKind.REMINDER_2H:
            return f"⏰ Через два часа\n\n{film_line}\n{when}\n\nДо встречи!"
        case NotificationKind.FEEDBACK_REMINDER:
            return f"⭐️ Как вам {film_line}?\n\nОцените фильм в приложении — это займёт полминуты."
        case NotificationKind.ADMIN_LOW_ATTENDANCE:
            confirmed = payload.get("confirmed", 0)
            needed = payload.get("min_attendance", 0)
            return (
                f"⚠️ Мало подтверждений\n\n{film_line}\n{when}\n\n"
                f"Придут {confirmed}, кворум {needed}. Решение о проведении за вами."
            )
        case NotificationKind.ROLE_GRANTED:
            # Что именно человек теперь умеет, решает вызывающий: список прав
            # живёт в roles.py, а не размазывается по шаблонам сообщений.
            title = payload.get("role_title", "новая роль")
            if payload.get("demoted"):
                return f"Ваша роль в клубе изменена: <b>{title}</b>."
            parts = [
                f"🔑 Вам выдали роль: <b>{title}</b>",
                payload.get("abilities"),
                "Откройте приложение — вкладка «Клуб» уже на месте.",
            ]
            return "\n\n".join(part for part in parts if part)
        case NotificationKind.ADMIN_BROADCAST:
            # Текст пишет человек, а сообщения уходят с parse_mode=HTML —
            # без экранирования любая угловая скобка в письме роняла бы
            # отправку всей рассылке.
            message = escape(payload.get("text") or "")
            if not message:
                return None
            # Подпись обязательна: сообщение приходит от бота, и человек должен
            # понимать, что это клуб, а не система напоминаний ошиблась.
            return f"📣 <b>Сообщение от клуба</b>\n\n{message}"
        case NotificationKind.BETA_OPENED:
            return (
                "🎉 Киноклуб открыт для всех!\n\n"
                "Код-приглашение больше не нужен — доступ у вас есть.\n"
                "Нажмите /start: покажу, как всё устроено."
            )
        case NotificationKind.FILM_REQUEST_RESOLVED:
            if payload.get("approved"):
                return "✅ Ваш фильм добавлен в каталог — можно отмечать."
            comment = payload.get("comment") or "без комментария"
            return f"Заявку на фильм отклонили.\n\n{comment}"
        case _:
            return None


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
                logger.warning("Не доставлено пользователю %s: %s", user.id, exc)
            else:
                # Сеть моргнула, Telegram ответил 429 или 500 — это про момент,
                # а не про адресата: пробуем снова позже.
                _postpone(notification, exc)

        # Коммит после каждого сообщения, а не раз на пачку: падение процесса
        # между отправкой и коммитом иначе разослало бы всю пачку повторно.
        await session.commit()

    return sent
