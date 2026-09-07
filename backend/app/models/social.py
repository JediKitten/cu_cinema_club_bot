"""Друзья и избранное в профиле (расширение по просьбе клуба)."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class Friendship(Base, CreatedAtMixin):
    """Одна строка — «я слежу за ним».

    Дружба не отдельная сущность, а две встречные строки: так «добавить»
    работает сразу, без ожидания ответа, а взаимность вычисляется запросом.
    Заявок, которые надо принимать, нет вовсе — принимать нечего.
    """

    __tablename__ = "friendships"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "friend_id", name="uq_friendship"),
        # Дружить с собой бессмысленно, и лента из собственных действий тоже.
        sa.CheckConstraint("user_id <> friend_id", name="friendship_not_self"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    friend_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)


class Favourite(Base, CreatedAtMixin):
    """До четырёх фильмов, которые человек показывает в профиле.

    Не отметка интереса: любимое кино не значит «хочу посмотреть», и в весах
    оно не участвует — это витрина, а не голос.
    """

    __tablename__ = "favourites"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "film_id", name="uq_favourite"),
        sa.UniqueConstraint("user_id", "position", name="uq_favourite_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    film_id: Mapped[int] = mapped_column(sa.ForeignKey("films.id"), index=True)
    position: Mapped[int]
