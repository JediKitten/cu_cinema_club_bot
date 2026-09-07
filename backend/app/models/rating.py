from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class FilmRating(Base, CreatedAtMixin):
    """Оценка фильма участником клуба (расширение по просьбе клуба).

    Пять звёзд с половинками, а хранится целым числом полубаллов: 1 — это
    ползвезды, 10 — пять. Дробей в базе нет, поэтому среднее считается точно,
    а «4.5» на экране не превращается в 4.499999.

    Оценивать можно из каталога, не дожидаясь показа: клуб выбирает кино в том
    числе по тому, что участники уже видели где-то ещё.
    """

    __tablename__ = "film_ratings"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "film_id", name="uq_film_rating"),
        sa.CheckConstraint("score BETWEEN 1 AND 10", name="film_rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    film_id: Mapped[int] = mapped_column(sa.ForeignKey("films.id"), index=True)
    # Полубаллы: 1..10. На экране делится пополам.
    score: Mapped[int]
    # Откуда пришла оценка: catalog — поставил сам, screening — форма после показа.
    source: Mapped[str] = mapped_column(sa.String(16), default="catalog", server_default="catalog")
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
