"""beta invite codes

Revision ID: b7c1d9e4f230
Revises: a1f2c3d4e5b6
Create Date: 2026-09-06 16:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1d9e4f230"
down_revision: str | None = "a1f2c3d4e5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Тот же список, что и в предыдущей миграции, плюс новое значение: виды
# уведомлений живут в CHECK, а не в нативном enum (§3).
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
)

ADDED = ("beta_opened",)


def _values(kinds: tuple[str, ...]) -> str:
    return ", ".join(f"'{kind}'" for kind in kinds)


def upgrade() -> None:
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("max_activations", sa.Integer(), server_default="1", nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_invite_codes_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invite_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_invite_codes_code")),
    )
    op.create_index(op.f("ix_invite_codes_code"), "invite_codes", ["code"], unique=False)
    op.create_index(
        op.f("ix_invite_codes_created_by"), "invite_codes", ["created_by"], unique=False
    )

    op.add_column("users", sa.Column("access_granted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("invite_code_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_invite_code_id_invite_codes"),
        "users",
        "invite_codes",
        ["invite_code_id"],
        ["id"],
    )

    # Все, кто пришёл до беты, остаются с доступом: закрывать клуб перед теми,
    # кто им уже пользуется, было бы обманом.
    op.execute("UPDATE users SET access_granted_at = now()")

    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS + ADDED)})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind IN (%s)" % _values(ADDED))
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint("notification_kind", "notifications", f"kind IN ({_values(KINDS)})")

    op.drop_constraint(op.f("fk_users_invite_code_id_invite_codes"), "users", type_="foreignkey")
    op.drop_column("users", "invite_code_id")
    op.drop_column("users", "access_granted_at")
    op.drop_index(op.f("ix_invite_codes_created_by"), table_name="invite_codes")
    op.drop_index(op.f("ix_invite_codes_code"), table_name="invite_codes")
    op.drop_table("invite_codes")
