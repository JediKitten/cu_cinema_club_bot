"""achievements: badges for taking part in the club

Правила и пороги живут в реестре кода (services/achievements.py) — в базе
только факт выдачи. Новая ачивка поэтому не требует миграции.

Revision ID: e9b530c4f172
Revises: d4c81f37a690
Create Date: 2026-09-11 16:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9b530c4f172"
down_revision: str | None = "d4c81f37a690"
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
)

ADDED = ("achievement_earned",)


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def upgrade() -> None:
    op.create_table(
        "achievements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "earned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_achievements_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_achievements")),
        sa.UniqueConstraint("user_id", "code", name="uq_achievement"),
    )
    op.create_index(op.f("ix_achievements_user_id"), "achievements", ["user_id"], unique=False)

    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS + ADDED)})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind IN (%s)" % _values(ADDED))
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint("notification_kind", "notifications", f"kind IN ({_values(KINDS)})")

    op.drop_index(op.f("ix_achievements_user_id"), table_name="achievements")
    op.drop_table("achievements")
