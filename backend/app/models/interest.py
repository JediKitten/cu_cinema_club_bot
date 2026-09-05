from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import InterestKind, RevokeReason, enum_col


class Interest(Base, CreatedAtMixin):
    """Сырое событие отметки. Вес НИКОГДА здесь не хранится (§4).

    Вес считается при чтении по текущим коэффициентам — иначе изменение периода
    полураспада не пересчитало бы историю.
    """

    __tablename__ = "interests"
    __table_args__ = (
        sa.Index("ix_interests_film_active", "film_id", "revoked_at"),
        sa.Index("ix_interests_user_active", "user_id", "revoked_at"),
        # Одна активная отметка на пару (пользователь, фильм) — «Желаемое» и
        # «Ближайшее» взаимоисключающие, вместе стоять не могут.
        # Частичный индекс: снятые отметки не мешают поставить заново.
        sa.Index(
            "uq_interests_active",
            "user_id",
            "film_id",
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    film_id: Mapped[int] = mapped_column(sa.ForeignKey("films.id"))
    kind: Mapped[InterestKind] = mapped_column(enum_col(InterestKind, "interest_kind"))
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    revoke_reason: Mapped[RevokeReason | None] = mapped_column(
        enum_col(RevokeReason, "revoke_reason")
    )
    # Уведомление об истечении SOON отправляем ровно один раз (идемпотентность крона).
    expiry_notified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Interest u{self.user_id} f{self.film_id} {self.kind}>"
