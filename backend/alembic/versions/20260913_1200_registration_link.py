"""screenings may carry their own registration link

Вуз ведёт учёт посещений отдельно от клуба, и ссылку на регистрацию админ
прикладывает к каждому показу: она у всех своя.

Revision ID: c7d31a95e408
Revises: a2c95e71d340
Create Date: 2026-09-13 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d31a95e408"
down_revision: str | None = "a2c95e71d340"
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
    "tournament_started",
    "tournament_round_opened",
    "tournament_finished",
    "achievement_earned",
)

ADDED = ("registration_link",)


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def upgrade() -> None:
    op.add_column(
        "screenings", sa.Column("registration_url", sa.String(length=500), nullable=True)
    )
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS + ADDED)})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind IN (%s)" % _values(ADDED))
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint("notification_kind", "notifications", f"kind IN ({_values(KINDS)})")
    op.drop_column("screenings", "registration_url")
