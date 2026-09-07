"""film ratings from the catalog

Revision ID: d41b6f902e73
Revises: c3a5e17b8d42
Create Date: 2026-09-07 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d41b6f902e73"
down_revision: str | None = "c3a5e17b8d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "film_ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("film_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), server_default="catalog", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("score BETWEEN 1 AND 10", name=op.f("ck_film_ratings_film_rating_range")),
        sa.ForeignKeyConstraint(
            ["film_id"], ["films.id"], name=op.f("fk_film_ratings_film_id_films")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_film_ratings_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_film_ratings")),
        sa.UniqueConstraint("user_id", "film_id", name="uq_film_rating"),
    )
    op.create_index(op.f("ix_film_ratings_user_id"), "film_ratings", ["user_id"], unique=False)
    op.create_index(op.f("ix_film_ratings_film_id"), "film_ratings", ["film_id"], unique=False)

    # Оценки, уже поставленные в форме после показа, — тот же рейтинг клуба.
    # Десятибалльная шкала формы это те же полубаллы, что и пять звёзд.
    # DISTINCT ON: один и тот же фильм могли оценить на двух показах.
    op.execute(
        """
        INSERT INTO film_ratings (user_id, film_id, score, source)
        SELECT DISTINCT ON (user_id, film_id) user_id, film_id, film_rating, 'screening'
        FROM feedback
        WHERE film_rating IS NOT NULL
        ORDER BY user_id, film_id, created_at DESC
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_film_ratings_film_id"), table_name="film_ratings")
    op.drop_index(op.f("ix_film_ratings_user_id"), table_name="film_ratings")
    op.drop_table("film_ratings")
