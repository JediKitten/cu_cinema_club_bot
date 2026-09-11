"""Турниры — голосование сеткой на любую тему (расширение по просьбе клуба).

Админ заводит тему («лучший злодей», «лучшая комедия») и набор вариантов,
клуб проходит сетку плей-офф: каждый этап длится сутки, дальше идёт
победитель пары. Вариант — либо фильм из каталога, либо своя карточка:
персонажа или сцену в каталоге не найти.

Голоса хранятся по одному на пару, а не счётчиком в паре: счётчик нельзя
пересчитать, если правила изменятся, и по нему не видно, кто уже голосовал.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import TournamentStatus, enum_col


class Tournament(Base, CreatedAtMixin):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(sa.String(120))
    description: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[TournamentStatus] = mapped_column(
        enum_col(TournamentStatus, "tournament_status"),
        default=TournamentStatus.DRAFT,
        index=True,
    )
    # Сколько длится один этап. Снимок настройки на момент старта: меняя
    # параметр, нельзя задним числом сдвинуть уже открытое голосование.
    stage_hours: Mapped[int] = mapped_column(default=24)
    # Номер идущего этапа: 1 — первый круг. 0 у черновика.
    current_round: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Ссылка на вариант, который сам ссылается на турнир: цикл разорван
    # use_alter, иначе SQLAlchemy не может упорядочить создание таблиц.
    winner_option_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("tournament_options.id", use_alter=True, name="fk_tournament_winner")
    )
    created_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"))


class TournamentOption(Base):
    """Вариант в сетке.

    `film_id` — не копия карточки: название и постер берутся из каталога при
    чтении, чтобы они не устаревали. Своя карточка описывается `title`
    и `image_url`.
    """

    __tablename__ = "tournament_options"
    __table_args__ = (sa.UniqueConstraint("tournament_id", "seed", name="uq_option_seed"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        sa.ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    # Посев: место в сетке, заданное админом. Он же решает ничью.
    seed: Mapped[int]
    title: Mapped[str] = mapped_column(sa.String(120))
    subtitle: Mapped[str | None] = mapped_column(sa.String(200))
    image_url: Mapped[str | None] = mapped_column(sa.Text)
    film_id: Mapped[int | None] = mapped_column(sa.ForeignKey("films.id"))


class TournamentMatch(Base):
    """Пара одного этапа.

    `option_b_id` пуст только у пары, собранной из ещё не сыгранного этапа —
    такого не бывает у нас, но модель это допускает, чтобы не городить
    заглушек при досрочном выбывании.
    """

    __tablename__ = "tournament_matches"
    __table_args__ = (
        sa.UniqueConstraint("tournament_id", "round_no", "position", name="uq_match_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        sa.ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    round_no: Mapped[int]
    position: Mapped[int]
    option_a_id: Mapped[int | None] = mapped_column(sa.ForeignKey("tournament_options.id"))
    option_b_id: Mapped[int | None] = mapped_column(sa.ForeignKey("tournament_options.id"))
    winner_option_id: Mapped[int | None] = mapped_column(sa.ForeignKey("tournament_options.id"))
    opens_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    closes_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))


class TournamentVote(Base, CreatedAtMixin):
    __tablename__ = "tournament_votes"
    __table_args__ = (sa.UniqueConstraint("match_id", "user_id", name="uq_tournament_vote"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(
        sa.ForeignKey("tournament_matches.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    option_id: Mapped[int] = mapped_column(sa.ForeignKey("tournament_options.id"))
