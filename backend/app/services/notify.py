"""Доставка уведомлений в Telegram (§7, §17).

Уведомления пишутся в таблицу теми, кто их порождает, а отправляются отдельно.
Так у отправки появляется одно место, где живут повторные попытки, и запись
переживает падение бота: неотправленное просто уйдёт следующим проходом.

Идемпотентность держится на `dedup_key`: повторный запуск фоновой задачи
не создаёт вторую запись, а значит и второго сообщения.
"""

import logging
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Film, Notification, Screening, Slot, User
from app.models.enums import NotificationKind

logger = logging.getLogger(__name__)

# Сколько сообщений отправляем за один проход. Telegram допускает ~30 сообщений
# в секунду; проход раз в несколько секунд с таким размером в лимит укладывается.
BATCH = 25


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
    rows = await session.execute(
        sa.select(Notification)
        .where(Notification.sent_at.is_(None), Notification.failed_reason.is_(None))
        .order_by(Notification.created_at)
        .limit(limit)
    )
    return list(rows.scalars())


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
    for notification in await pending(session):
        user = await session.get(User, notification.user_id)
        if user is None or user.tg_id is None:
            notification.failed_reason = "нет привязки Telegram"
            continue

        film, slot = await _context(session, notification)
        text = render(
            notification.kind, film, _when(slot, tz_convert), notification.payload or {}
        )
        if text is None:
            # Вид уведомления есть, а текста для него ещё нет. Помечаем, чтобы
            # запись не крутилась в очереди вечно.
            notification.failed_reason = "нет шаблона"
            continue

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
            # Заблокировал бота, удалил аккаунт, сеть моргнула — записываем
            # причину, чтобы очередь не встала намертво из-за одного адресата.
            notification.failed_reason = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning("Не доставлено пользователю %s: %s", user.id, exc)

    await session.commit()
    return sent
