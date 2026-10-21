"""special weeks: theme note and a pre-fixed screening time

Хэллоуинский показ: время назначено заранее, клуб выбирает только фильм.
Цикл получает плашку с темой и признак «вечер уже выбран».

Revision ID: b2e8c4f71a39
Revises: a7d3e9f21c84
Create Date: 2026-10-21 16:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2e8c4f71a39"
down_revision: str | None = "a7d3e9f21c84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rounds", sa.Column("theme_note", sa.Text(), nullable=True))
    op.add_column(
        "rounds",
        sa.Column("fixed_slot", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("rounds", "fixed_slot")
    op.drop_column("rounds", "theme_note")
