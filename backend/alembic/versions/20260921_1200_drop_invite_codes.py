"""drop the invite-code gate

Закрытая бета кончилась: клуб открыт, и вход по кодам больше не нужен.
Вместе с ним уходят таблица кодов, обе колонки пользователя и вид
уведомления «клуб открыт для всех» — рассказывать об открытии больше некому.

Приглашение на фильм (`referrals`) — другая история и остаётся: это ссылка
«позвать друга на конкретное кино», а не пропуск в клуб.

Revision ID: d5a1c83b7e60
Revises: c4f70b8e29a1
Create Date: 2026-09-21 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5a1c83b7e60"
down_revision: str | None = "c4f70b8e29a1"
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

GONE = ("beta_opened",)


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def upgrade() -> None:
    # Внешний ключ уедет вместе с колонкой: Postgres снимает ограничения,
    # построенные на ней одной. Отдельный drop_constraint только привязал бы
    # миграцию к имени, которое где-то может отличаться.
    op.drop_column("users", "invite_code_id")
    op.drop_column("users", "access_granted_at")
    op.drop_table("invite_codes")

    op.execute(f"DELETE FROM notifications WHERE kind IN ({_values(GONE)})")
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS)})"
    )

    # Параметр §13 больше ничего не значит: реестр о нём не знает, а строка
    # в базе только путала бы того, кто заглянет в таблицу.
    op.execute("DELETE FROM settings WHERE key = 'beta_invite_required'")


def downgrade() -> None:
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("max_activations", sa.Integer(), server_default="1", nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_invite_codes_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invite_codes")),
    )
    op.create_index(op.f("ix_invite_codes_code"), "invite_codes", ["code"], unique=True)
    op.create_index(
        op.f("ix_invite_codes_created_by"), "invite_codes", ["created_by"], unique=False
    )
    op.add_column(
        "users", sa.Column("access_granted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("invite_code_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_invite_code_id_invite_codes",
        "users",
        "invite_codes",
        ["invite_code_id"],
        ["id"],
    )

    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS + GONE)})"
    )
