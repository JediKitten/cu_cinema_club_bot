from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import UserRole, enum_col


class User(Base, CreatedAtMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Один Telegram-аккаунт = один аккаунт в системе (§12).
    # nullable — веб-регистрация создаёт аккаунт до привязки TG, но до неё
    # функции недоступны; см. require_linked() в app/core/auth.py.
    tg_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True)
    tg_username: Mapped[str | None] = mapped_column(sa.String(64))
    email: Mapped[str | None] = mapped_column(sa.String(255), unique=True)
    display_name: Mapped[str] = mapped_column(sa.String(128))
    role: Mapped[UserRole] = mapped_column(
        enum_col(UserRole, "user_role"), default=UserRole.USER, server_default="user"
    )
    tz: Mapped[str] = mapped_column(
        sa.String(64), default="Europe/Moscow", server_default="Europe/Moscow"
    )
    photo_url: Mapped[str | None] = mapped_column(sa.String(512))
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Показывали ли знакомство с ботом. Хранится, а не выводится из created_at:
    # аккаунт может завестись до первого /start — например, по чужой ссылке.
    onboarded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=sa.true())
    # Когда Telegram ответил «бот заблокирован». Пока пометка свежая, рассылки
    # обходят человека стороной: каждое сообщение ему — заведомый отказ.
    # Снимается, как только он снова пишет боту.
    bot_blocked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id} {self.display_name!r} {self.role}>"
