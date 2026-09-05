"""Фоновые задачи цикла (§7, §17).

Все задачи обязаны быть идемпотентными: повторный запуск не должен приводить
к дублю уведомлений. Здесь это достигается двумя способами — отметкой на самой
записи (`reminded_24h_at`) и ключом `dedup_key` у уведомления.
"""

import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Confirmation, Screening, Slot, User
from app.models.enums import (
    ConfirmationState,
    NotificationKind,
    ScreeningStatus,
    UserRole,
)
from app.services.notify import queue
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Насколько раньше срока допустимо отправить напоминание. Без окна задача,
# запущенная раз в пять минут, пропустила бы момент и не напомнила вовсе.
WINDOW = timedelta(minutes=30)


async def _upcoming(
    session: AsyncSession, hours: int
) -> list[tuple[Screening, Slot]]:
    """Показы, до которых осталось около `hours` часов."""
    now = datetime.now(UTC)
    target = now + timedelta(hours=hours)
    rows = await session.execute(
        sa.select(Screening, Slot)
        .join(Slot, Slot.id == Screening.slot_id)
        .where(
            Screening.status == ScreeningStatus.SCHEDULED,
            Slot.starts_at > now,
            Slot.starts_at <= target + WINDOW,
        )
    )
    return [(s, slot) for s, slot in rows]


async def send_reminders(session: AsyncSession, hours: int) -> int:
    """Напоминание подтвердившим за `hours` часов до показа (§7)."""
    field = Confirmation.reminded_24h_at if hours >= 24 else Confirmation.reminded_2h_at
    kind = NotificationKind.REMINDER_24H if hours >= 24 else NotificationKind.REMINDER_2H

    created = 0
    for screening, _slot in await _upcoming(session, hours):
        confirmations = (
            (
                await session.execute(
                    sa.select(Confirmation).where(
                        Confirmation.screening_id == screening.id,
                        Confirmation.state == ConfirmationState.CONFIRMED,
                        field.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for confirmation in confirmations:
            await queue(
                session,
                confirmation.user_id,
                kind,
                dedup_key=f"{kind}:{screening.id}:{confirmation.user_id}",
                payload={"screening_id": screening.id},
            )
            # Отметка на подтверждении — вторая линия защиты помимо dedup_key:
            # даже если запись уведомления удалят, повторно мы не напомним.
            setattr(confirmation, field.key, datetime.now(UTC))
            created += 1

    await session.commit()
    return created


async def warn_low_attendance(session: AsyncSession) -> int:
    """Предупреждение админам, если подтверждений меньше кворума (§7).

    Автоматической отмены нет: решение о проведении принимает человек.
    """
    values = await SettingsService(session).all()
    hours = int(values["early_warning_hours"])
    minimum = int(values["min_attendance"])

    admins = (
        (
            await session.execute(
                sa.select(User.id).where(
                    User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN]), User.is_active
                )
            )
        )
        .scalars()
        .all()
    )
    if not admins:
        return 0

    created = 0
    for screening, _slot in await _upcoming(session, hours):
        confirmed = (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Confirmation)
                .where(
                    Confirmation.screening_id == screening.id,
                    Confirmation.state == ConfirmationState.CONFIRMED,
                )
            )
            or 0
        )
        if confirmed >= minimum:
            continue

        for admin_id in admins:
            # Один раз на показ и админа, сколько бы раз ни выполнилась задача.
            if await queue(
                session,
                admin_id,
                NotificationKind.ADMIN_LOW_ATTENDANCE,
                dedup_key=f"low:{screening.id}:{admin_id}",
                payload={
                    "screening_id": screening.id,
                    "confirmed": confirmed,
                    "min_attendance": minimum,
                },
            ):
                created += 1

    await session.commit()
    return created


async def run_all(session: AsyncSession) -> dict[str, int]:
    """Один проход по всем периодическим задачам."""
    result = {
        "reminders_24h": await send_reminders(session, 24),
        "reminders_2h": await send_reminders(session, 2),
        "low_attendance": await warn_low_attendance(session),
    }
    if any(result.values()):
        logger.info("Фоновые задачи: %s", result)
    return result
