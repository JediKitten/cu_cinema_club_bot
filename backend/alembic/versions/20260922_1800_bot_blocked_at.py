"""users.bot_blocked_at

Заблокировавший бота человек оставался в каждой рассылке: каждое сообщение
ему давало отказ, а админ видел в «получат сообщение» и его. Пометку ставит
рассылка при отказе «бот заблокирован», снимает — любое сообщение боту.

Прошлые отказы переносим сразу: они уже лежат в очереди уведомлений.

Revision ID: f3c9a2d15b47
Revises: e7b2f41c96d8
Create Date: 2026-09-22 18:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3c9a2d15b47"
down_revision: str | None = "e7b2f41c96d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("bot_blocked_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE users SET bot_blocked_at = last.at
        FROM (
            SELECT user_id, max(created_at) AS at
            FROM notifications
            WHERE failed_reason ILIKE '%blocked%'
            GROUP BY user_id
        ) AS last
        WHERE users.id = last.user_id
          -- Дошедшее после отказа сообщение значит, что его уже разблокировали.
          AND NOT EXISTS (
              SELECT 1 FROM notifications AS later
              WHERE later.user_id = last.user_id AND later.sent_at > last.at
          )
        """
    )


def downgrade() -> None:
    op.drop_column("users", "bot_blocked_at")
