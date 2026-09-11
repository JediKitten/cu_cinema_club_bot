"""Ачивки — бейджи за участие в клубе (расширение по просьбе клуба).

Хранится только факт получения: правила и пороги живут в реестре кода
(`services/achievements.py`), как и параметры §13. Новая ачивка не требует
миграции, а забытая — не ломает старые записи.

Дата нужна не для красоты: поздравить человека надо ровно один раз, и без
отметки «когда выдали» отличить новую ачивку от старой нечем.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Achievement(Base):
    __tablename__ = "achievements"
    __table_args__ = (sa.UniqueConstraint("user_id", "code", name="uq_achievement"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(sa.String(64))
    earned_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
