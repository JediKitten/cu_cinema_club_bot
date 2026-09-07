"""friends and profile favourites

Revision ID: c3a5e17b8d42
Revises: b7c1d9e4f230
Create Date: 2026-09-06 20:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3a5e17b8d42"
down_revision: str | None = "b7c1d9e4f230"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "friendships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("friend_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("user_id <> friend_id", name=op.f("ck_friendships_friendship_not_self")),
        sa.ForeignKeyConstraint(
            ["friend_id"], ["users.id"], name=op.f("fk_friendships_friend_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_friendships_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_friendships")),
        sa.UniqueConstraint("user_id", "friend_id", name="uq_friendship"),
    )
    op.create_index(op.f("ix_friendships_user_id"), "friendships", ["user_id"], unique=False)
    op.create_index(op.f("ix_friendships_friend_id"), "friendships", ["friend_id"], unique=False)

    op.create_table(
        "favourites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("film_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["film_id"], ["films.id"], name=op.f("fk_favourites_film_id_films")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_favourites_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_favourites")),
        sa.UniqueConstraint("user_id", "film_id", name="uq_favourite"),
        sa.UniqueConstraint("user_id", "position", name="uq_favourite_position"),
    )
    op.create_index(op.f("ix_favourites_user_id"), "favourites", ["user_id"], unique=False)
    op.create_index(op.f("ix_favourites_film_id"), "favourites", ["film_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_favourites_film_id"), table_name="favourites")
    op.drop_index(op.f("ix_favourites_user_id"), table_name="favourites")
    op.drop_table("favourites")
    op.drop_index(op.f("ix_friendships_friend_id"), table_name="friendships")
    op.drop_index(op.f("ix_friendships_user_id"), table_name="friendships")
    op.drop_table("friendships")
