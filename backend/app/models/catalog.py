from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import FilmRequestStatus, FilmStatus, enum_col


class Film(Base, CreatedAtMixin):
    __tablename__ = "films"
    __table_args__ = (
        # Триграммный индекс для поиска по подстроке с опечатками.
        # Требует CREATE EXTENSION pg_trgm — создаётся в первой миграции.
        sa.Index(
            "ix_films_title_trgm",
            "title_ru",
            "title_orig",
            postgresql_using="gin",
            postgresql_ops={"title_ru": "gin_trgm_ops", "title_orig": "gin_trgm_ops"},
        ),
        sa.Index("ix_films_status_year", "status", "year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(unique=True, index=True)
    kp_id: Mapped[int | None] = mapped_column(unique=True)

    title_ru: Mapped[str] = mapped_column(sa.String(512))
    title_orig: Mapped[str | None] = mapped_column(sa.String(512))
    year: Mapped[int | None]
    runtime_min: Mapped[int | None]
    overview: Mapped[str | None] = mapped_column(sa.Text)
    # Постеры не храним: только path, URL собирается на лету с CDN TMDB (§11).
    poster_path: Mapped[str | None] = mapped_column(sa.String(255))
    backdrop_path: Mapped[str | None] = mapped_column(sa.String(255))
    trailer_key: Mapped[str | None] = mapped_column(sa.String(64))
    genres: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(64)), default=list, server_default="{}"
    )
    directors: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(128)), default=list, server_default="{}"
    )

    ext_rating: Mapped[float | None] = mapped_column(sa.Float)
    ext_votes: Mapped[int | None]
    # Рейтинг Кинопоиска подтягивается лениво и кэшируется на 30 дней (§11).
    kp_rating: Mapped[float | None] = mapped_column(sa.Float)
    kp_votes: Mapped[int | None]
    kp_fetched_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    status: Mapped[FilmStatus] = mapped_column(
        enum_col(FilmStatus, "film_status"),
        default=FilmStatus.ACTIVE,
        server_default="active",
    )
    added_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    tmdb_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Film {self.id} {self.title_ru!r} ({self.year})>"


class FilmRequest(Base, CreatedAtMixin):
    """Заявка «не нашёл фильм» — очередь модерации (§4)."""

    __tablename__ = "film_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    raw_title: Mapped[str] = mapped_column(sa.String(512))
    raw_year: Mapped[int | None]
    note: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[FilmRequestStatus] = mapped_column(
        enum_col(FilmRequestStatus, "film_request_status"),
        default=FilmRequestStatus.PENDING,
        server_default="pending",
        index=True,
    )
    resolved_film_id: Mapped[int | None] = mapped_column(sa.ForeignKey("films.id"))
    resolved_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    resolution_comment: Mapped[str | None] = mapped_column(sa.Text)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class TmdbSyncState(Base):
    """Курсор ночного крона по /movie/changes, чтобы дозагрузка была идемпотентной."""

    __tablename__ = "tmdb_sync_state"

    key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class Watch(Base, CreatedAtMixin):
    """«Просмотрено» — отдельно от интереса (§8, расширено по просьбе клуба).

    Не отметка и веса не несёт: посмотренный фильм можно оставить в «Желаемом»,
    чтобы сходить снова. Поэтому отдельная таблица, а не третий вид Interest.
    """

    __tablename__ = "watches"
    __table_args__ = (sa.UniqueConstraint("user_id", "film_id", name="uq_watch"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    film_id: Mapped[int] = mapped_column(sa.ForeignKey("films.id"), index=True)
    # manual — отметил сам, attendance — зафиксирован приход на сеанс.
    source: Mapped[str] = mapped_column(sa.String(16), default="manual", server_default="manual")
    screening_id: Mapped[int | None] = mapped_column(sa.ForeignKey("screenings.id"))
