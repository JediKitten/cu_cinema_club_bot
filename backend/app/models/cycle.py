from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import (
    AttendanceMethod,
    ConfirmationState,
    RoundStage,
    ScreeningStatus,
    ShortlistSource,
    enum_col,
)


class Hall(Base):
    __tablename__ = "halls"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(128))
    capacity: Mapped[int]
    active: Mapped[bool] = mapped_column(default=True, server_default=sa.true())


class Round(Base, CreatedAtMixin):
    """Один цикл: от среза этапа 1 до последнего показа недели (§2)."""

    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Понедельник недели показов. Уникален — один цикл на неделю.
    week_start: Mapped[date] = mapped_column(sa.Date, unique=True)
    stage: Mapped[RoundStage] = mapped_column(
        enum_col(RoundStage, "round_stage"),
        default=RoundStage.COLLECTING,
        server_default="collecting",
        index=True,
    )
    shortlist_locked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    schedule_locked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    low_activity: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    # Если все вечера заблокированы — показов на неделе нет (§3).
    skipped_reason: Mapped[str | None] = mapped_column(sa.Text)


class ShortlistItem(Base):
    __tablename__ = "shortlist_items"
    __table_args__ = (sa.UniqueConstraint("round_id", "film_id", name="uq_shortlist_round_film"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(sa.ForeignKey("rounds.id"), index=True)
    film_id: Mapped[int] = mapped_column(sa.ForeignKey("films.id"))
    source: Mapped[ShortlistSource] = mapped_column(enum_col(ShortlistSource, "shortlist_source"))
    position: Mapped[int]
    # Вес на момент среза — снимок для аналитики, не источник истины.
    weight_snapshot: Mapped[float | None] = mapped_column(sa.Float)


class AutopilotProposal(Base, CreatedAtMixin):
    """Автопилот считает решение ВСЕГДА, даже когда админ работает вручную,
    и показывает его рядом как подсказку (§5). Храним отдельно от факта."""

    __tablename__ = "autopilot_proposals"
    __table_args__ = (sa.UniqueConstraint("round_id", "stage", name="uq_autopilot_round_stage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(sa.ForeignKey("rounds.id"), index=True)
    stage: Mapped[int]  # 1 — шорт-лист, 2 — расписание
    payload: Mapped[dict] = mapped_column(sa.JSON)
    applied: Mapped[bool] = mapped_column(default=False, server_default=sa.false())


class Slot(Base):
    """Слот описан как (зал, дата, время начала, длительность) даже при одном зале
    и фиксированных 19:00 — чтобы §19 (несколько залов, блоки) не ломал модель."""

    __tablename__ = "slots"
    __table_args__ = (sa.UniqueConstraint("round_id", "hall_id", "starts_at", name="uq_slot_slot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Пусто у слотов ручных событий: они назначаются вне недельного цикла.
    round_id: Mapped[int | None] = mapped_column(sa.ForeignKey("rounds.id"), index=True)
    hall_id: Mapped[int] = mapped_column(sa.ForeignKey("halls.id"))
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    duration_min: Mapped[int] = mapped_column(default=180, server_default="180")
    blocked: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    blocked_reason: Mapped[str | None] = mapped_column(sa.Text)


class FilmVote(Base, CreatedAtMixin):
    """Этап 2: «пошёл бы на этот фильм». Множественный выбор, не ранжирование."""

    __tablename__ = "film_votes"
    __table_args__ = (
        sa.UniqueConstraint("round_id", "user_id", "film_id", name="uq_vote"),
        sa.Index("ix_film_votes_round_film", "round_id", "film_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(sa.ForeignKey("rounds.id"))
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    film_id: Mapped[int] = mapped_column(sa.ForeignKey("films.id"))


class Availability(Base, CreatedAtMixin):
    """Этап 2: «свободен в этот вечер»."""

    __tablename__ = "availability"
    __table_args__ = (
        sa.UniqueConstraint("round_id", "user_id", "slot_id", name="uq_availability"),
        sa.Index("ix_availability_round_slot", "round_id", "slot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(sa.ForeignKey("rounds.id"))
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    slot_id: Mapped[int] = mapped_column(sa.ForeignKey("slots.id"))


class Screening(Base, CreatedAtMixin):
    __tablename__ = "screenings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Оба поля пусты у ручных событий: они не принадлежат циклу, а фильм может
    # быть ещё не объявлен («ждите анонса»).
    round_id: Mapped[int | None] = mapped_column(sa.ForeignKey("rounds.id"), index=True)
    film_id: Mapped[int | None] = mapped_column(sa.ForeignKey("films.id"), index=True)
    slot_id: Mapped[int] = mapped_column(sa.ForeignKey("slots.id"))
    # Назначено администратором вручную, в обход алгоритма.
    is_manual: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    # Заголовок и подпись — для события без фильма.
    title: Mapped[str | None] = mapped_column(sa.String(200))
    note: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[ScreeningStatus] = mapped_column(
        enum_col(ScreeningStatus, "screening_status"),
        default=ScreeningStatus.SCHEDULED,
        server_default="scheduled",
    )
    expected_attendance: Mapped[int | None]
    decided_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(sa.Text)
    # Секрет для ротируемого кода присутствия (§8, схема в духе TOTP).
    attendance_secret: Mapped[str | None] = mapped_column(sa.String(64))

    __table_args__ = (
        # Один показ на слот. Отменённые не блокируют слот — частичный индекс.
        sa.Index(
            "uq_screening_slot",
            "slot_id",
            unique=True,
            postgresql_where=sa.text("status <> 'cancelled'"),
        ),
        # Один фильм не более одного раза за цикл (§6).
        # Один фильм не более одного раза за цикл (§6). Ручные события сюда
        # не попадают: у них нет ни цикла, ни обязательного фильма.
        sa.Index(
            "uq_screening_round_film",
            "round_id",
            "film_id",
            unique=True,
            postgresql_where=sa.text(
                "status <> 'cancelled' AND round_id IS NOT NULL AND film_id IS NOT NULL"
            ),
        ),
    )


class CancelRequest(Base, CreatedAtMixin):
    """Модератор не отменяет сеанс сам — создаёт заявку, ждёт подтверждения
    любого админа. До подтверждения сеанс считается активным (§9)."""

    __tablename__ = "cancel_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    screening_id: Mapped[int] = mapped_column(sa.ForeignKey("screenings.id"), index=True)
    requested_by: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(sa.Text)
    approved_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    approved: Mapped[bool | None]


class Confirmation(Base, CreatedAtMixin):
    __tablename__ = "confirmations"
    __table_args__ = (
        sa.UniqueConstraint("screening_id", "user_id", name="uq_confirmation"),
        sa.Index("ix_confirmations_screening_state", "screening_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    screening_id: Mapped[int] = mapped_column(sa.ForeignKey("screenings.id"))
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    state: Mapped[ConfirmationState] = mapped_column(
        enum_col(ConfirmationState, "confirmation_state")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Отмена в последние late_cancel_hours фиксируется в статистике (§7).
    was_late_cancel: Mapped[bool] = mapped_column(default=False, server_default=sa.false())
    reminded_24h_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    reminded_2h_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (sa.UniqueConstraint("screening_id", "user_id", name="uq_attendance"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    screening_id: Mapped[int] = mapped_column(sa.ForeignKey("screenings.id"), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    method: Mapped[AttendanceMethod] = mapped_column(
        enum_col(AttendanceMethod, "attendance_method")
    )
    marked_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    # Кто отметил: для method=manual — модератор, иначе сам пользователь.
    marked_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))


class Feedback(Base, CreatedAtMixin):
    __tablename__ = "feedback"
    __table_args__ = (
        sa.UniqueConstraint("screening_id", "user_id", name="uq_feedback"),
        sa.CheckConstraint(
            "film_rating IS NULL OR film_rating BETWEEN 1 AND 10",
            name="film_rating_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    screening_id: Mapped[int] = mapped_column(sa.ForeignKey("screenings.id"), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    # Пусто у ручного события без фильма (встреча клуба, «ждите анонса»):
    # оценивать там нечего, а рассказать, как прошло, — есть что.
    film_id: Mapped[int | None] = mapped_column(sa.ForeignKey("films.id"), index=True)
    film_rating: Mapped[int | None]
    review_text: Mapped[str | None] = mapped_column(sa.Text)
    # Оценка организации НЕ входит в рейтинг фильма (§8) — отдельные поля.
    org_sound: Mapped[int | None]
    org_picture: Mapped[int | None]
    org_hall: Mapped[int | None]
    org_time: Mapped[int | None]
    org_comment: Mapped[str | None] = mapped_column(sa.Text)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
