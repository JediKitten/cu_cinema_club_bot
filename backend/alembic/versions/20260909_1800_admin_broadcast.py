"""admin broadcast: a message kind for anything the templates do not cover

Виды уведомлений живут в CHECK, а не в нативном enum (§3): добавить значение
в нативный тип внутри транзакции нельзя, а пересобрать CHECK — можно.

Revision ID: c3d81e46a970
Revises: f7a2c93d5e18
Create Date: 2026-09-09 18:00:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3d81e46a970"
down_revision: str | None = "f7a2c93d5e18"
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
)

ADDED = ("admin_broadcast",)


def _values(kinds: tuple[str, ...]) -> str:
    return ", ".join(f"'{kind}'" for kind in kinds)


def upgrade() -> None:
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS + ADDED)})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind IN (%s)" % _values(ADDED))
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint("notification_kind", "notifications", f"kind IN ({_values(KINDS)})")
