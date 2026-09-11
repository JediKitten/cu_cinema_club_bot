"""screenings may be held in english

Свойство сеанса, а не фильма: один и тот же фильм клуб может показать
и с дубляжом, и в оригинале. §19 называл «дубляж/субтитры» отложенным —
это его первый кусок, тот, что понадобился ачивкам.

Revision ID: f1a6d20b8c34
Revises: e9b530c4f172
Create Date: 2026-09-11 18:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a6d20b8c34"
down_revision: str | None = "e9b530c4f172"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "screenings",
        sa.Column("in_english", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("screenings", "in_english")
