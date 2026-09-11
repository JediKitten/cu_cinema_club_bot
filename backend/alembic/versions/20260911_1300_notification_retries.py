"""notification retries: attempts and next_attempt_at

Revision ID: a7f2c9d13b64
Revises: c3d81e46a970
Create Date: 2026-09-11 13:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7f2c9d13b64"
down_revision: str | None = "c3d81e46a970"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "notifications",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Уже похороненные уведомления намеренно не воскрешаем. Соблазн велик —
    # среди них есть потерянные по сетевой ошибке, — но вместе с ними в очередь
    # вернулись бы приглашения на прошедшие показы и напоминания «через два
    # часа» о том, что было неделю назад. Повторные попытки начинают работать
    # с этого момента и только для новых записей.


def downgrade() -> None:
    op.drop_column("notifications", "next_attempt_at")
    op.drop_column("notifications", "attempts")
