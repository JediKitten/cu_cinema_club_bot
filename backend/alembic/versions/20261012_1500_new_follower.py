"""notify a user when someone adds them as a friend

Подписка работала молча: о новом подписчике человек узнавал, только
случайно открыв «Друзей». Уведомление зовёт добавить в ответ.

Revision ID: a7d3e9f21c84
Revises: f3c9a2d15b47
Create Date: 2026-10-12 15:00:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d3e9f21c84"
down_revision: str | None = "f3c9a2d15b47"
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
    "admin_autopilot_soon",
    "admin_low_attendance",
    "admin_cancel_request",
    "admin_film_request",
    "role_granted",
    "admin_broadcast",
    "registration_link",
    "achievement_earned",
    "tournament_started",
    "tournament_round_opened",
    "tournament_finished",
)

ADDED = ("new_follower",)


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def upgrade() -> None:
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS + ADDED)})"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM notifications WHERE kind IN ({_values(ADDED)})")
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint("notification_kind", "notifications", f"kind IN ({_values(KINDS)})")
