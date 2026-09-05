"""Ручные события (§10, расширение по просьбе клуба).

Администратор назначает показ или встречу на любое время, в обход алгоритма.
Такое событие не принадлежит недельному циклу и не участвует в его правилах:
фильм может быть ещё не объявлен, а время — любым, не только вечером в 19:00.
"""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Film, Hall, Screening, Slot
from app.models.enums import ScreeningStatus
from app.services.rounds import ensure_hall


class EventError(ValueError):
    """Причину показываем администратору как есть."""


async def create(
    session: AsyncSession,
    *,
    starts_at: datetime,
    actor_id: int,
    film_id: int | None = None,
    title: str | None = None,
    note: str | None = None,
    duration_min: int = 180,
    hall_id: int | None = None,
) -> Screening:
    """Заводит событие вне цикла.

    Без фильма событие обязано иметь заголовок — иначе в расписании появится
    строка, о которой нельзя сказать вообще ничего.
    """
    if film_id is None and not (title or "").strip():
        raise EventError("Укажите фильм или заголовок события")

    if film_id is not None and await session.get(Film, film_id) is None:
        raise EventError("Фильм не найден")

    if starts_at.tzinfo is None:
        raise EventError("Время должно быть с часовым поясом")

    hall = await session.get(Hall, hall_id) if hall_id else await ensure_hall(session)
    if hall is None:
        raise EventError("Зал не найден")

    busy = await session.scalar(
        sa.select(Screening.id)
        .join(Slot, Slot.id == Screening.slot_id)
        .where(
            Slot.hall_id == hall.id,
            Slot.starts_at == starts_at,
            Screening.status != ScreeningStatus.CANCELLED,
        )
    )
    if busy:
        raise EventError("На это время в зале уже что-то назначено")

    slot = Slot(round_id=None, hall_id=hall.id, starts_at=starts_at, duration_min=duration_min)
    session.add(slot)
    await session.flush()

    event = Screening(
        round_id=None,
        film_id=film_id,
        slot_id=slot.id,
        is_manual=True,
        title=(title or "").strip() or None,
        note=(note or "").strip() or None,
        decided_by=actor_id,
        decided_at=datetime.now(UTC),
    )
    session.add(event)
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="screening",
            action="create_manual",
            payload={"starts_at": starts_at.isoformat(), "film_id": film_id, "title": title},
        )
    )
    await session.commit()
    return event


async def upcoming(session: AsyncSession, within_days: int = 60) -> list[Screening]:
    """Будущие ручные события — они показываются вне зависимости от цикла."""
    horizon = datetime.now(UTC) + timedelta(days=within_days)
    rows = await session.execute(
        sa.select(Screening)
        .join(Slot, Slot.id == Screening.slot_id)
        .where(
            Screening.is_manual.is_(True),
            Screening.status != ScreeningStatus.CANCELLED,
            Slot.starts_at >= datetime.now(UTC) - timedelta(hours=6),
            Slot.starts_at <= horizon,
        )
        .order_by(Slot.starts_at)
    )
    return list(rows.scalars())


async def reveal(
    session: AsyncSession, event_id: int, film_id: int, actor_id: int
) -> Screening:
    """Раскрывает фильм у объявленного заранее события.

    Именно ради этого события и заводят «ждите анонса»: время уже известно,
    а название объявляют позже.
    """
    event = await session.get(Screening, event_id)
    if event is None or not event.is_manual:
        raise EventError("Событие не найдено")
    if await session.get(Film, film_id) is None:
        raise EventError("Фильм не найден")

    event.film_id = film_id
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="screening",
            entity_id=event_id,
            action="reveal",
            payload={"film_id": film_id},
        )
    )
    await session.commit()
    return event
