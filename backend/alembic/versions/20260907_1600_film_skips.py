"""film skips from the swipe deck

Revision ID: e58c2a1b7f40
Revises: d41b6f902e73
Create Date: 2026-09-07 16:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e58c2a1b7f40"
down_revision: str | None = "d41b6f902e73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "film_skips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("film_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["film_id"], ["films.id"], name=op.f("fk_film_skips_film_id_films")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_film_skips_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_film_skips")),
        sa.UniqueConstraint("user_id", "film_id", name="uq_film_skip"),
    )
    op.create_index(op.f("ix_film_skips_user_id"), "film_skips", ["user_id"], unique=False)
    op.create_index(op.f("ix_film_skips_film_id"), "film_skips", ["film_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_film_skips_film_id"), table_name="film_skips")
    op.drop_index(op.f("ix_film_skips_user_id"), table_name="film_skips")
    op.drop_table("film_skips")
