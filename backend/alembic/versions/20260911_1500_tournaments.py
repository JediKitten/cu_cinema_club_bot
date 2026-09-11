"""tournaments: playoff-style voting on any topic

Виды уведомлений живут в CHECK, а не в нативном enum (§3) — добавляя турнирные,
пересобираем ограничение целиком.

Revision ID: d4c81f37a690
Revises: b1e4f7a2c085
Create Date: 2026-09-11 15:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4c81f37a690"
down_revision: str | None = "b1e4f7a2c085"
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
)

ADDED = ("tournament_started", "tournament_round_opened", "tournament_finished")

STATUSES = ("draft", "running", "finished", "cancelled")


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


def upgrade() -> None:
    op.create_table(
        "tournaments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage_hours", sa.Integer(), nullable=False),
        sa.Column("current_round", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("winner_option_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(f"status IN ({_values(STATUSES)})", name="tournament_status"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_tournaments_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournaments")),
    )
    op.create_index(op.f("ix_tournaments_status"), "tournaments", ["status"], unique=False)

    op.create_table(
        "tournament_options",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("subtitle", sa.String(length=200), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("film_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["film_id"], ["films.id"], name=op.f("fk_tournament_options_film_id_films")
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_tournament_options_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_options")),
        sa.UniqueConstraint("tournament_id", "seed", name="uq_option_seed"),
    )
    op.create_index(
        op.f("ix_tournament_options_tournament_id"),
        "tournament_options",
        ["tournament_id"],
        unique=False,
    )

    # Турнир ссылается на вариант, вариант — на турнир: ограничение вешаем
    # после обеих таблиц, иначе создать их нельзя ни в каком порядке.
    op.create_foreign_key(
        "fk_tournament_winner", "tournaments", "tournament_options", ["winner_option_id"], ["id"]
    )

    op.create_table(
        "tournament_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("option_a_id", sa.Integer(), nullable=True),
        sa.Column("option_b_id", sa.Integer(), nullable=True),
        sa.Column("winner_option_id", sa.Integer(), nullable=True),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["option_a_id"],
            ["tournament_options.id"],
            name=op.f("fk_tournament_matches_option_a_id_tournament_options"),
        ),
        sa.ForeignKeyConstraint(
            ["option_b_id"],
            ["tournament_options.id"],
            name=op.f("fk_tournament_matches_option_b_id_tournament_options"),
        ),
        sa.ForeignKeyConstraint(
            ["winner_option_id"],
            ["tournament_options.id"],
            name=op.f("fk_tournament_matches_winner_option_id_tournament_options"),
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournaments.id"],
            name=op.f("fk_tournament_matches_tournament_id_tournaments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_matches")),
        sa.UniqueConstraint("tournament_id", "round_no", "position", name="uq_match_slot"),
    )
    op.create_index(
        op.f("ix_tournament_matches_tournament_id"),
        "tournament_matches",
        ["tournament_id"],
        unique=False,
    )

    op.create_table(
        "tournament_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("option_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["tournament_matches.id"],
            name=op.f("fk_tournament_votes_match_id_tournament_matches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["option_id"],
            ["tournament_options.id"],
            name=op.f("fk_tournament_votes_option_id_tournament_options"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_tournament_votes_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament_votes")),
        sa.UniqueConstraint("match_id", "user_id", name="uq_tournament_vote"),
    )
    op.create_index(
        op.f("ix_tournament_votes_match_id"), "tournament_votes", ["match_id"], unique=False
    )
    op.create_index(
        op.f("ix_tournament_votes_user_id"), "tournament_votes", ["user_id"], unique=False
    )

    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint(
        "notification_kind", "notifications", f"kind IN ({_values(KINDS + ADDED)})"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind IN (%s)" % _values(ADDED))
    op.drop_constraint("notification_kind", "notifications", type_="check")
    op.create_check_constraint("notification_kind", "notifications", f"kind IN ({_values(KINDS)})")

    op.drop_table("tournament_votes")
    op.drop_table("tournament_matches")
    op.drop_constraint("fk_tournament_winner", "tournaments", type_="foreignkey")
    op.drop_table("tournament_options")
    op.drop_table("tournaments")
