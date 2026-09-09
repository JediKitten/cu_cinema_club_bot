from enum import StrEnum

import sqlalchemy as sa


def enum_col(py_enum: type[StrEnum], name: str) -> sa.Enum:
    """VARCHAR + CHECK вместо нативного типа Postgres.

    Спек требует расширяемости без ломающих миграций (§3): добавить значение
    в нативный pg enum внутри транзакции нельзя, а пересобрать CHECK — можно.
    """
    return sa.Enum(
        py_enum,
        native_enum=False,
        create_constraint=True,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        length=32,
    )


class UserRole(StrEnum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]


_ROLE_RANK = {
    UserRole.USER: 0,
    UserRole.MODERATOR: 1,
    UserRole.ADMIN: 2,
    UserRole.SUPERADMIN: 3,
}


class FilmStatus(StrEnum):
    ACTIVE = "active"
    HIDDEN = "hidden"
    PENDING_MODERATION = "pending_moderation"


class FilmRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class InterestKind(StrEnum):
    WISHLIST = "wishlist"
    SOON = "soon"


class RevokeReason(StrEnum):
    MANUAL = "manual"
    EXPIRED = "expired"
    WATCHED = "watched"
    # Нажата вторая кнопка: состояния взаимоисключающие, прежнее снимается.
    SUPERSEDED = "superseded"


class RoundStage(StrEnum):
    COLLECTING = "collecting"
    SHORTLIST_REVIEW = "shortlist_review"
    SLOT_VOTING = "slot_voting"
    SCHEDULE_REVIEW = "schedule_review"
    PUBLISHED = "published"
    RUNNING = "running"
    CLOSED = "closed"


class ShortlistSource(StrEnum):
    AUTO_WEIGHT = "auto_weight"
    AUTO_COVERAGE = "auto_coverage"
    ADMIN = "admin"


class ScreeningStatus(StrEnum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class ConfirmationState(StrEnum):
    CONFIRMED = "confirmed"
    WAITLIST = "waitlist"
    CANCELLED = "cancelled"


class AttendanceMethod(StrEnum):
    QR = "qr"
    CODE = "code"
    MANUAL = "manual"


class NotificationKind(StrEnum):
    SOON_EXPIRED = "soon_expired"
    SHORTLIST_PUBLISHED = "shortlist_published"
    SCHEDULE_PUBLISHED = "schedule_published"
    SCREENING_CHANGED = "screening_changed"
    SCREENING_CANCELLED = "screening_cancelled"
    REMINDER_24H = "reminder_24h"
    REMINDER_2H = "reminder_2h"
    WAITLIST_PROMOTED = "waitlist_promoted"
    FEEDBACK_REMINDER = "feedback_reminder"
    NO_SHOW = "no_show"
    LATE_CANCEL = "late_cancel"
    FILM_REQUEST_RESOLVED = "film_request_resolved"
    ADMIN_SHORTLIST_READY = "admin_shortlist_ready"
    ADMIN_MATRIX_READY = "admin_matrix_ready"
    ADMIN_AUTOPILOT_RAN = "admin_autopilot_ran"
    ADMIN_LOW_ATTENDANCE = "admin_low_attendance"
    ADMIN_CANCEL_REQUEST = "admin_cancel_request"
    ADMIN_FILM_REQUEST = "admin_film_request"
    # Роль выдана: человек должен узнать об этом, а не наткнуться на новую вкладку.
    ROLE_GRANTED = "role_granted"
    # Бета кончилась: код больше не нужен, и тем, кто на нём застрял, надо сказать.
    BETA_OPENED = "beta_opened"
    # Произвольное сообщение от админа: клубу нужно говорить и то, чего нет
    # ни в одном шаблоне.
    ADMIN_BROADCAST = "admin_broadcast"
