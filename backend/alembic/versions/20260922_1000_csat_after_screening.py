"""csat survey after each screening

Клуб отчитывается перед вузом, и отчёт нужен не по ощущениям, а по цифрам:
как прошёл вечер целиком, как сам фильм, как обсуждение после. Четыре поля
организации (звук, картинка, зал, время) уходят — их не спрашивал ни один
экран, и ни одной заполненной строки по ним нет.

Revision ID: e7b2f41c96d8
Revises: d5a1c83b7e60
Create Date: 2026-09-22 10:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7b2f41c96d8"
down_revision: str | None = "d5a1c83b7e60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SKIPS = ("absent", "unsure")


def upgrade() -> None:
    op.add_column("feedback", sa.Column("visit_rating", sa.Integer(), nullable=True))
    op.add_column("feedback", sa.Column("discussion_rating", sa.Integer(), nullable=True))
    op.add_column(
        "feedback",
        sa.Column(
            "discussion_skip",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "discussion_skip",
        "feedback",
        "discussion_skip IS NULL OR discussion_skip IN ('absent', 'unsure')",
    )
    op.create_check_constraint(
        "visit_rating_range", "feedback", "visit_rating IS NULL OR visit_rating BETWEEN 1 AND 10"
    )
    op.create_check_constraint(
        "discussion_rating_range",
        "feedback",
        "discussion_rating IS NULL OR discussion_rating BETWEEN 1 AND 10",
    )
    op.create_check_constraint(
        "discussion_one_answer",
        "feedback",
        "discussion_rating IS NULL OR discussion_skip IS NULL",
    )

    # Оценка организации по четырём осям осталась от спека и не спрашивалась
    # ни одним экраном: колонки пустые во всех строках.
    for column in ("org_sound", "org_picture", "org_hall", "org_time", "org_comment"):
        op.drop_column("feedback", column)


def downgrade() -> None:
    for column in ("org_sound", "org_picture", "org_hall", "org_time"):
        op.add_column("feedback", sa.Column(column, sa.Integer(), nullable=True))
    op.add_column("feedback", sa.Column("org_comment", sa.Text(), nullable=True))

    op.drop_constraint("discussion_one_answer", "feedback", type_="check")
    op.drop_constraint("discussion_rating_range", "feedback", type_="check")
    op.drop_constraint("visit_rating_range", "feedback", type_="check")
    op.drop_constraint("discussion_skip", "feedback", type_="check")
    op.drop_column("feedback", "discussion_skip")
    op.drop_column("feedback", "discussion_rating")
    op.drop_column("feedback", "visit_rating")
