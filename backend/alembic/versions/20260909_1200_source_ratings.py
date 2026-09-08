"""ratings kept per source: tmdb and kinopoisk side by side

Каталог наполнялся из двух источников, а рейтинг хранился один — «внешний».
Из-за этого фильм, приехавший с Кинопоиска, показывал оценку КП с подписью
TMDB, и сортировать «по оценкам TMDB» было не по чему.

Revision ID: f7a2c93d5e18
Revises: e58c2a1b7f40
Create Date: 2026-09-09 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a2c93d5e18"
down_revision: str | None = "e58c2a1b7f40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("films", sa.Column("tmdb_rating", sa.Float(), nullable=True))
    op.add_column("films", sa.Column("tmdb_votes", sa.Integer(), nullable=True))
    op.add_column("films", sa.Column("kp_top250", sa.Integer(), nullable=True))

    # У фильмов, приехавших из TMDB, «внешний» рейтинг — это и есть TMDB.
    # Их узнаём по постеру: у Кинопоиска в poster_path лежит абсолютный URL.
    op.execute(
        """
        UPDATE films
           SET tmdb_rating = ext_rating, tmdb_votes = ext_votes
         WHERE tmdb_id IS NOT NULL
           AND (poster_path IS NULL OR poster_path NOT LIKE 'http%')
        """
    )
    # Зеркально: у завезённых с Кинопоиска внешний рейтинг — это рейтинг КП.
    op.execute(
        """
        UPDATE films
           SET kp_rating = COALESCE(kp_rating, ext_rating),
               kp_votes = COALESCE(kp_votes, ext_votes)
         WHERE kp_id IS NOT NULL
        """
    )
    # Сортировка «по оценкам» идёт по этим колонкам и на полутора тысячах строк
    # без индекса заставляла бы читать таблицу целиком на каждой странице.
    op.create_index("ix_films_tmdb_rating", "films", ["tmdb_rating"])
    op.create_index("ix_films_kp_rating", "films", ["kp_rating"])


def downgrade() -> None:
    op.drop_index("ix_films_kp_rating", table_name="films")
    op.drop_index("ix_films_tmdb_rating", table_name="films")
    op.drop_column("films", "kp_top250")
    op.drop_column("films", "tmdb_votes")
    op.drop_column("films", "tmdb_rating")
