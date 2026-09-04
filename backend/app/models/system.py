from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import NotificationKind, enum_col


class Setting(Base):
    """Параметры §13. Значение — JSONB, тип и валидация задаются реестром
    в app/services/settings.py, а не схемой БД."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class AuditLog(Base, CreatedAtMixin):
    __tablename__ = "audit_log"
    __table_args__ = (sa.Index("ix_audit_entity", "entity", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    entity: Mapped[str] = mapped_column(sa.String(64))
    entity_id: Mapped[int | None]
    action: Mapped[str] = mapped_column(sa.String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    comment: Mapped[str | None] = mapped_column(sa.Text)


class Notification(Base, CreatedAtMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        sa.Index("ix_notifications_user_unsent", "user_id", "sent_at"),
        # Ключ идемпотентности: повторный запуск фоновой задачи не должен
        # порождать дубль уведомления (§17).
        sa.UniqueConstraint("dedup_key", name="uq_notifications_dedup_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    kind: Mapped[NotificationKind] = mapped_column(enum_col(NotificationKind, "notification_kind"))
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    dedup_key: Mapped[str | None] = mapped_column(sa.String(255))
    sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    failed_reason: Mapped[str | None] = mapped_column(sa.Text)
