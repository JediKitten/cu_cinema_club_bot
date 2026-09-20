"""warn admins an hour before the autopilot decides

Автопилот собирает шорт-лист и расставляет показы сам. Узнать об этом админ
мог только постфактум — из «автопилот отработал». Предупреждение за час даёт
возможность решить самому, пока решение ещё за человеком.

Revision ID: c4f70b8e29a1
Revises: b8e4c1d70f52
Create Date: 2026-09-21 10:00:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f70b8e29a1"
down_revision: str | None = "b8e4c1d70f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
    "soon_expired",
    "shortlist_published",
    "schedule_published",
    "screening_changed",
    "screening_cancelled",
    "reminder_24h",
    "reminder_2h",
    "waitlist_promoted",
    "feedback_reminder",
    "no_show",
    "late_cancel",
    "film_request_resolved",
    "admin_shortlist_ready",
    "admin_matrix_ready",
    "admin_autopilot_ran",
    "admin_low_attendance",
    "admin_cancel_request",
    "admin_film_request",
    "role_granted",
    "beta_opened",
    "admin_broadcast",
    "registration_link",
    "achievement_earned",
    "tournament_started",
    "tournament_round_opened",
    "tournament_finished",
)

ADDED = ("admin_autopilot_soon",)


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def upgrade() -> None:
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS + ADDED)})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind IN (%s)" % _values(ADDED))
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS)})"
    )
