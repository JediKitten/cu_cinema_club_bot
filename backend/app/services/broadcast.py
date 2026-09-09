"""Рассылка от лица бота (расширение по просьбе клуба).

Клубу регулярно нужно сказать людям то, чего нет ни в одном шаблоне: перенос
из-за ремонта, просьба принести стулья, объявление о встрече. Раньше это можно
было сделать только руками в чате, где половина людей не состоит.

Сообщение не отправляется отсюда: оно кладётся в ту же очередь уведомлений,
что и всё остальное. Так у рассылки бесплатно появляются повторные попытки,
пометка «заблокировал бота» вместо потерянного сообщения и общий с остальными
уведомлениями темп отправки — Telegram не любит всплесков.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Confirmation, Film, Screening, Slot, User
from app.models.enums import ConfirmationState, NotificationKind, ScreeningStatus
from app.services import notify

# Телеграм не принимает сообщения длиннее 4096 символов, а к тексту рассылки
# добавляется ещё и заголовок.
MAX_LENGTH = 3500

# Кому можно писать. «Всем» — это все, кто вообще запускал бота: рассылка
# клубная, а не рекламная, и делить аудиторию по правам смысла нет.
ALL = "all"
SCREENING = "screening"


class BroadcastError(ValueError):
    """Причину показываем как есть."""


@dataclass(frozen=True, slots=True)
class Delivery:
    """Сколько человек получат сообщение и куда оно ушло."""

    recipients: int
    audience: str
    screening_id: int | None = None


def _everyone():
    return sa.select(User.id).where(User.is_active, User.tg_id.is_not(None))


def _signed_up(screening_id: int):
    """Записавшиеся на показ: и те, кто в зале, и те, кто в очереди.

    Отменившиеся не в счёт — они уже сказали, что не придут, и напоминание
    о показе для них не новость, а спам.
    """
    return sa.select(Confirmation.user_id).where(
        Confirmation.screening_id == screening_id,
        Confirmation.state.in_([ConfirmationState.CONFIRMED, ConfirmationState.WAITLIST]),
    )


async def audience_size(
    session: AsyncSession, audience: str, screening_id: int | None = None
) -> int:
    """Сколько человек получат сообщение — цифру показываем до отправки.

    Рассылку нельзя отозвать, поэтому «отправить сорока трём» должно стоять
    перед кнопкой, а не выясняться после.
    """
    query = await _recipients_query(session, audience, screening_id)
    return await session.scalar(sa.select(sa.func.count()).select_from(query.subquery())) or 0


async def _recipients_query(session: AsyncSession, audience: str, screening_id: int | None):
    if audience == ALL:
        return _everyone()
    if audience == SCREENING:
        if screening_id is None:
            raise BroadcastError("Не выбран показ")
        if await session.get(Screening, screening_id) is None:
            raise BroadcastError("Показ не найден")
        # Пересечение с живыми пользователями: у записи мог остаться человек,
        # которого потом отключили.
        return _everyone().where(User.id.in_(_signed_up(screening_id)))
    raise BroadcastError("Неизвестная аудитория")


@dataclass(frozen=True, slots=True)
class Target:
    """Показ, которому можно написать, — с числом записавшихся."""

    id: int
    starts_at: object
    title: str
    signed_up: int


async def screenings(session: AsyncSession) -> list[Target]:
    """Ближайшие показы: и цикловые, и ручные события.

    Написать «зал переехал» нужно тем, кто придёт, а откуда взялся показ —
    из голосования или из ручного анонса — для рассылки безразлично.
    """
    signed = (
        sa.select(
            Confirmation.screening_id.label("screening_id"),
            sa.func.count().label("people"),
        )
        .where(
            Confirmation.state.in_([ConfirmationState.CONFIRMED, ConfirmationState.WAITLIST])
        )
        .group_by(Confirmation.screening_id)
        .subquery()
    )
    rows = await session.execute(
        sa.select(Screening, Slot.starts_at, Film.title_ru, signed.c.people)
        .join(Slot, Slot.id == Screening.slot_id)
        .outerjoin(Film, Film.id == Screening.film_id)
        .outerjoin(signed, signed.c.screening_id == Screening.id)
        .where(
            Screening.status != ScreeningStatus.CANCELLED,
            # Шесть часов назад, а не «сейчас»: идущему сегодня показу написать
            # всё ещё есть смысл — например, что задерживаемся.
            Slot.starts_at >= datetime.now(UTC) - timedelta(hours=6),
        )
        .order_by(Slot.starts_at)
    )
    return [
        Target(
            id=screening.id,
            starts_at=starts_at,
            title=title or screening.title or "Показ",
            signed_up=people or 0,
        )
        for screening, starts_at, title, people in rows
    ]


async def send(
    session: AsyncSession,
    actor_id: int,
    text: str,
    audience: str = ALL,
    screening_id: int | None = None,
) -> Delivery:
    """Кладёт сообщение в очередь каждому адресату.

    Отдельная запись на человека, а не одна на рассылку: очередь умеет
    повторять попытки и помечать неудачи поимённо, и рассылка ведёт себя
    ровно так же, как любое другое уведомление.
    """
    message = text.strip()
    if not message:
        raise BroadcastError("Пустое сообщение отправлять некому")
    if len(message) > MAX_LENGTH:
        raise BroadcastError(f"Сообщение длиннее {MAX_LENGTH} символов")

    query = await _recipients_query(session, audience, screening_id)
    recipients = list((await session.execute(query)).scalars())

    # Один ключ на рассылку: он делает записи уникальными по паре
    # (рассылка, человек), так что повторный вызов не задвоит сообщение,
    # а две разные рассылки с одинаковым текстом дойдут обе.
    batch = uuid.uuid4().hex[:12]
    payload = {"text": message, "batch": batch}
    if screening_id is not None:
        # Ключ `screening_id` понимает `notify._context`: к сообщению
        # подтянутся название фильма и время, если шаблон их попросит.
        payload["screening_id"] = screening_id

    for user_id in recipients:
        await notify.queue(
            session,
            user_id,
            NotificationKind.ADMIN_BROADCAST,
            f"broadcast:{batch}:{user_id}",
            payload,
        )

    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="broadcast",
            entity_id=screening_id,
            action="send",
            payload={
                "audience": audience,
                "recipients": len(recipients),
                "batch": batch,
                # Текст в журнале целиком: «кто и что разослал» — единственный
                # способ разобраться, если рассылка окажется ошибкой.
                "text": message,
            },
        )
    )
    await session.commit()
    return Delivery(recipients=len(recipients), audience=audience, screening_id=screening_id)
