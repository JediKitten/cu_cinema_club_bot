"""Ачивки — бейджи за участие в клубе (расширение по просьбе клуба).

У ачивки из реестра хранится только факт получения: правила и пороги живут
в коде (`services/achievements.py`), как и параметры §13. Новая ачивка
не требует миграции, а забытая — не ломает старые записи.

Исключение — именные: их админ придумывает под конкретного человека, и такой
текст в реестр не положить. У них заполнены `title`, `description` и `tier`.

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

    # --- Именная ачивка, выданная админом вручную ---------------------------
    #
    # Её правила нет и не может быть в реестре: она придумана под конкретного
    # человека («за то, что притащил проектор»). Поэтому текст живёт в самой
    # строке, а не в коде, и только у таких записей эти поля заполнены.
    title: Mapped[str | None] = mapped_column(sa.String(120))
    description: Mapped[str | None] = mapped_column(sa.String(200))
    tier: Mapped[str | None] = mapped_column(sa.String(16))
    granted_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
