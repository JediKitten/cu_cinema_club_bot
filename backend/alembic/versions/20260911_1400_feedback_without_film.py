"""feedback may belong to an event without a film

Revision ID: b1e4f7a2c085
Revises: a7f2c9d13b64
Create Date: 2026-09-11 14:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1e4f7a2c085"
down_revision: str | None = "a7f2c9d13b64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ручное событие бывает без фильма — встреча клуба или показ «ждите анонса».
    # Отзыв о нём осмыслен (как прошло, как звук, как зал), а оценивать нечего.
    op.alter_column("feedback", "film_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM feedback WHERE film_id IS NULL")
    op.alter_column("feedback", "film_id", existing_type=sa.Integer(), nullable=False)
