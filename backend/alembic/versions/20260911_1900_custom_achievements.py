"""hand-granted achievements carry their own text

Именную ачивку админ придумывает под конкретного человека — её правила
в реестре кода быть не может, поэтому текст живёт в самой строке.

Revision ID: a2c95e71d340
Revises: f1a6d20b8c34
Create Date: 2026-09-11 19:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c95e71d340"
down_revision: str | None = "f1a6d20b8c34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("achievements", sa.Column("title", sa.String(length=120), nullable=True))
    op.add_column("achievements", sa.Column("description", sa.String(length=200), nullable=True))
    op.add_column("achievements", sa.Column("tier", sa.String(length=16), nullable=True))
    op.add_column("achievements", sa.Column("granted_by", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_achievements_granted_by_users"), "achievements", "users", ["granted_by"], ["id"]
    )


def downgrade() -> None:
    op.execute("DELETE FROM achievements WHERE title IS NOT NULL")
    op.drop_constraint(op.f("fk_achievements_granted_by_users"), "achievements", type_="foreignkey")
    op.drop_column("achievements", "granted_by")
    op.drop_column("achievements", "tier")
    op.drop_column("achievements", "description")
    op.drop_column("achievements", "title")
