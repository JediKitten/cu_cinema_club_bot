"""a whole week may be held in english

Пометка недели, а не отдельного показа: клуб объявляет «эта неделя на
английском» до того, как фильм выбран голосованием. Показ, назначенный
в такую неделю, наследует признак — иначе его пришлось бы проставлять
вручную и вспоминать об этом каждый раз.

Revision ID: b8e4c1d70f52
Revises: c7d31a95e408
Create Date: 2026-09-17 16:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e4c1d70f52"
down_revision: str | None = "c7d31a95e408"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rounds",
        sa.Column("in_english", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("rounds", "in_english")
