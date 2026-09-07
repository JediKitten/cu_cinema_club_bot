"""Профили, друзья и лента (расширение по просьбе клуба).

Клуб — это люди, а не только расписание: чужие оценки убеждают сходить сильнее
любого рейтинга. Поэтому у каждого участника есть профиль с четырьмя любимыми
фильмами, а за теми, чей вкус совпадает, можно следить.

Ничего нового не хранится ради ленты: она собирается из тех же событий, что уже
есть — отметки, просмотры и оценки.
"""

from dataclasses import dataclass, field
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Favourite, Feedback, Film, Friendship, Interest, User, Watch
from app.models.enums import FilmStatus, InterestKind

# Четыре фильма — ровно строка постеров в профиле. Больше превращает витрину
# в ещё один список, которых в приложении и так хватает.
MAX_FAVOURITES = 4

FEED_LIMIT = 40


class SocialError(ValueError):
    """Причину показываем как есть."""


@dataclass(slots=True)
class Relation:
    """Как двое связаны. Дружба — это две встречные подписки."""

    following: bool
    follower: bool

    @property
    def friends(self) -> bool:
        return self.following and self.follower


@dataclass(slots=True)
class FeedItem:
    kind: str
    at: datetime
    user_id: int
    user_name: str
    user_photo: str | None
    film_id: int
    film_title: str
    film_year: int | None
    film_poster: str | None
    rating: int | None = None
    text: str | None = None


@dataclass(slots=True)
class Profile:
    id: int
    display_name: str
    tg_username: str | None
    photo_url: str | None
    role: str
    joined_at: datetime
    favourites: list[Film] = field(default_factory=list)
    marks: int = 0
    watched: int = 0
    ratings: int = 0
    average_rating: float | None = None
    friends: int = 0
    relation: Relation | None = None
    recent: list[FeedItem] = field(default_factory=list)


async def relation(session: AsyncSession, viewer_id: int, other_id: int) -> Relation:
    if viewer_id == other_id:
        return Relation(following=False, follower=False)
    rows = (
        await session.execute(
            sa.select(Friendship.user_id, Friendship.friend_id).where(
                sa.or_(
                    sa.and_(Friendship.user_id == viewer_id, Friendship.friend_id == other_id),
                    sa.and_(Friendship.user_id == other_id, Friendship.friend_id == viewer_id),
                )
            )
        )
    ).all()
    pairs = set(rows)
    return Relation(
        following=(viewer_id, other_id) in pairs,
        follower=(other_id, viewer_id) in pairs,
    )


async def follow(session: AsyncSession, viewer_id: int, other_id: int) -> Relation:
    if viewer_id == other_id:
        raise SocialError("Себя добавлять не нужно")
    if await session.get(User, other_id) is None:
        raise SocialError("Пользователь не найден")

    existing = await session.scalar(
        sa.select(Friendship.id).where(
            Friendship.user_id == viewer_id, Friendship.friend_id == other_id
        )
    )
    if existing is None:
        session.add(Friendship(user_id=viewer_id, friend_id=other_id))
        await session.commit()
    return await relation(session, viewer_id, other_id)


async def unfollow(session: AsyncSession, viewer_id: int, other_id: int) -> Relation:
    await session.execute(
        sa.delete(Friendship).where(
            Friendship.user_id == viewer_id, Friendship.friend_id == other_id
        )
    )
    await session.commit()
    return await relation(session, viewer_id, other_id)


async def following_ids(session: AsyncSession, user_id: int) -> list[int]:
    rows = await session.execute(
        sa.select(Friendship.friend_id).where(Friendship.user_id == user_id)
    )
    return list(rows.scalars())


async def circle(session: AsyncSession, user_id: int) -> dict[str, list[User]]:
    """Кого я добавил и кто добавил меня. Взаимные — друзья."""
    mine = set(await following_ids(session, user_id))
    theirs = set(
        (
            await session.execute(
                sa.select(Friendship.user_id).where(Friendship.friend_id == user_id)
            )
        )
        .scalars()
        .all()
    )

    ids = mine | theirs
    if not ids:
        return {"friends": [], "following": [], "followers": []}

    people = {
        user.id: user
        for user in (await session.execute(sa.select(User).where(User.id.in_(ids)))).scalars()
    }

    def sorted_people(subset: set[int]) -> list[User]:
        return sorted(
            (people[uid] for uid in subset if uid in people), key=lambda u: u.display_name
        )

    return {
        "friends": sorted_people(mine & theirs),
        "following": sorted_people(mine - theirs),
        "followers": sorted_people(theirs - mine),
    }


async def _film_rows(session: AsyncSession, film_ids: set[int]) -> dict[int, Film]:
    if not film_ids:
        return {}
    return {
        film.id: film
        for film in (
            await session.execute(sa.select(Film).where(Film.id.in_(film_ids)))
        ).scalars()
    }


async def feed(
    session: AsyncSession, user_ids: list[int], limit: int = FEED_LIMIT
) -> list[FeedItem]:
    """Что делали те, за кем следят: оценки, отметки, просмотры.

    Три запроса вместо UNION: у событий разные поля, а собрать их в общий
    список дешевле в Python, чем приводить к одной форме в SQL.
    """
    if not user_ids:
        return []

    raw: list[tuple[str, datetime, int, int, int | None, str | None]] = []

    for feedback, in await session.execute(
        sa.select(Feedback)
        .where(
            Feedback.user_id.in_(user_ids),
            sa.or_(Feedback.film_rating.is_not(None), Feedback.review_text.is_not(None)),
        )
        .order_by(Feedback.created_at.desc())
        .limit(limit)
    ):
        raw.append(
            (
                "rating",
                feedback.created_at,
                feedback.user_id,
                feedback.film_id,
                feedback.film_rating,
                feedback.review_text,
            )
        )

    for interest in (
        await session.execute(
            sa.select(Interest)
            .where(Interest.user_id.in_(user_ids), Interest.revoked_at.is_(None))
            .order_by(Interest.created_at.desc())
            .limit(limit)
        )
    ).scalars():
        raw.append(
            (
                "soon" if interest.kind == InterestKind.SOON else "wishlist",
                interest.created_at,
                interest.user_id,
                interest.film_id,
                None,
                None,
            )
        )

    for watch in (
        await session.execute(
            sa.select(Watch)
            .where(Watch.user_id.in_(user_ids))
            .order_by(Watch.created_at.desc())
            .limit(limit)
        )
    ).scalars():
        raw.append(("watched", watch.created_at, watch.user_id, watch.film_id, None, None))

    raw.sort(key=lambda item: item[1], reverse=True)
    raw = raw[:limit]

    films = await _film_rows(session, {item[3] for item in raw})
    people = {
        user.id: user
        for user in (
            await session.execute(sa.select(User).where(User.id.in_({item[2] for item in raw})))
        ).scalars()
    }

    items = []
    for kind, at, user_id, film_id, rating, text in raw:
        film, author = films.get(film_id), people.get(user_id)
        if film is None or author is None:
            continue
        items.append(
            FeedItem(
                kind=kind,
                at=at,
                user_id=author.id,
                user_name=author.display_name,
                user_photo=author.photo_url,
                film_id=film.id,
                film_title=film.title_ru,
                film_year=film.year,
                film_poster=film.poster_path,
                rating=rating,
                text=text,
            )
        )
    return items


async def favourites(session: AsyncSession, user_id: int) -> list[Film]:
    rows = await session.execute(
        sa.select(Film)
        .join(Favourite, Favourite.film_id == Film.id)
        .where(Favourite.user_id == user_id)
        .order_by(Favourite.position)
    )
    return list(rows.scalars())


async def set_favourites(session: AsyncSession, user_id: int, film_ids: list[int]) -> list[Film]:
    """Заменяет витрину целиком: порядок задаёт сам человек."""
    if len(film_ids) > MAX_FAVOURITES:
        raise SocialError(f"В профиль помещается {MAX_FAVOURITES} фильма")
    if len(set(film_ids)) != len(film_ids):
        raise SocialError("Фильмы повторяются")

    known = set(
        (
            await session.execute(
                sa.select(Film.id).where(Film.id.in_(film_ids), Film.status != FilmStatus.HIDDEN)
            )
        )
        .scalars()
        .all()
    )
    missing = [film_id for film_id in film_ids if film_id not in known]
    if missing:
        raise SocialError("Фильм не найден")

    await session.execute(sa.delete(Favourite).where(Favourite.user_id == user_id))
    # Сброс до вставки: иначе уникальность (user_id, position) ломается при
    # перестановке уже выбранных фильмов.
    await session.flush()
    session.add_all(
        Favourite(user_id=user_id, film_id=film_id, position=position)
        for position, film_id in enumerate(film_ids)
    )
    await session.commit()
    return await favourites(session, user_id)


async def profile(session: AsyncSession, viewer_id: int, user_id: int) -> Profile | None:
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        return None

    marks = (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Interest)
            .where(Interest.user_id == user_id, Interest.revoked_at.is_(None))
        )
        or 0
    )
    watched = (
        await session.scalar(
            sa.select(sa.func.count()).select_from(Watch).where(Watch.user_id == user_id)
        )
        or 0
    )
    average, ratings = (
        await session.execute(
            sa.select(sa.func.avg(Feedback.film_rating), sa.func.count(Feedback.film_rating)).where(
                Feedback.user_id == user_id, Feedback.film_rating.is_not(None)
            )
        )
    ).one()

    mutual = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Friendship)
        .where(
            Friendship.user_id == user_id,
            Friendship.friend_id.in_(
                sa.select(Friendship.user_id).where(Friendship.friend_id == user_id)
            ),
        )
    )

    return Profile(
        id=user.id,
        display_name=user.display_name,
        tg_username=user.tg_username,
        photo_url=user.photo_url,
        role=user.role,
        joined_at=user.created_at,
        favourites=await favourites(session, user_id),
        marks=marks,
        watched=watched,
        ratings=ratings,
        average_rating=round(float(average), 2) if ratings else None,
        friends=mutual or 0,
        relation=await relation(session, viewer_id, user_id),
        recent=await feed(session, [user_id], limit=10),
    )


async def search(session: AsyncSession, query: str, exclude_id: int, limit: int = 20) -> list[User]:
    """Поиск людей по имени или @username — чтобы было кого добавлять."""
    pattern = f"%{query.strip()}%"
    rows = await session.execute(
        sa.select(User)
        .where(
            User.is_active,
            User.id != exclude_id,
            User.tg_id.is_not(None),
            sa.or_(User.display_name.ilike(pattern), User.tg_username.ilike(pattern)),
        )
        .order_by(User.display_name)
        .limit(limit)
    )
    return list(rows.scalars())
