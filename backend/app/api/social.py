"""Профили, друзья и лента (расширение по просьбе клуба)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.db import get_session
from app.models import Film, User
from app.schemas import (
    CircleOut,
    FavouritesIn,
    FeedItemOut,
    FilmBrief,
    PersonBrief,
    ProfileOut,
)
from app.services import social
from app.services.social import SocialError
from app.services.tmdb import TmdbError, ensure_film, poster_url

router = APIRouter(prefix="/api", tags=["social"])


def _film(film: Film) -> FilmBrief:
    return FilmBrief(
        id=film.id,
        tmdb_id=film.tmdb_id,
        title_ru=film.title_ru,
        title_orig=film.title_orig,
        year=film.year,
        poster_url=poster_url(film.poster_path),
        genres=list(film.genres or []),
        directors=list(film.directors or []),
    )


def _item(item: social.FeedItem) -> FeedItemOut:
    return FeedItemOut(
        kind=item.kind,
        at=item.at,
        user_id=item.user_id,
        user_name=item.user_name,
        user_photo=item.user_photo,
        film_id=item.film_id,
        film_title=item.film_title,
        film_year=item.film_year,
        film_poster=poster_url(item.film_poster),
        rating=item.rating,
        text=item.text,
    )


def _person(user: User, relation: social.Relation | None = None) -> PersonBrief:
    return PersonBrief(
        id=user.id,
        display_name=user.display_name,
        tg_username=user.tg_username,
        photo_url=user.photo_url,
        friends=bool(relation and relation.friends),
        following=bool(relation and relation.following),
        follower=bool(relation and relation.follower),
    )


@router.get("/people", response_model=list[PersonBrief])
async def find_people(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
) -> list[PersonBrief]:
    """Участники клуба: поиск по имени, а без запроса — все.

    Найти человека поиском можно, только если знаешь, кого ищешь; новичку
    список нужен целиком.
    """
    found = (
        await social.search(session, q, exclude_id=user.id)
        if q
        else await social.everyone(session, exclude_id=user.id)
    )
    links = await social.relations(session, user.id, [person.id for person in found])
    return [_person(person, links.get(person.id)) for person in found]


@router.get("/me/circle", response_model=CircleOut)
async def my_circle(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> CircleOut:
    """Друзья (взаимно), подписки и подписчики — тремя списками.

    Разделение честнее общего списка «друзья»: односторонняя связь ею
    не является, и делать вид, что является, значит вводить в заблуждение.
    """
    groups = await social.circle(session, user.id)
    return CircleOut(
        friends=[_person(person, social.Relation(True, True)) for person in groups["friends"]],
        following=[_person(person, social.Relation(True, False)) for person in groups["following"]],
        followers=[_person(person, social.Relation(False, True)) for person in groups["followers"]],
    )


@router.get("/me/feed", response_model=list[FeedItemOut])
async def my_feed(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[FeedItemOut]:
    """Что смотрели и как оценивали те, за кем вы следите."""
    items = await social.feed(session, await social.following_ids(session, user.id))
    return [_item(item) for item in items]


@router.put("/me/favourites", response_model=list[FilmBrief])
async def set_favourites(
    body: FavouritesIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[FilmBrief]:
    """Четыре фильма в профиле. Порядок задаёт сам человек.

    Любимый фильм можно выбрать и из TMDB: в каталог он попадёт прямо здесь —
    ровно как при первой отметке интереса. Иначе в витрину профиля попадала бы
    только та сотня, что кто-то уже завёл до вас.
    """
    film_ids: list[int] = []
    for ref in body.films:
        if ref.film_id is not None:
            film_ids.append(ref.film_id)
            continue
        if ref.tmdb_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Нужен film_id или tmdb_id"
            )
        try:
            film_ids.append((await ensure_film(session, ref.tmdb_id)).id)
        except TmdbError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"TMDB недоступен: {exc}") from exc

    try:
        films = await social.set_favourites(session, user.id, film_ids)
    except SocialError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return [_film(film) for film in films]


@router.post("/users/{user_id}/friend", response_model=PersonBrief)
async def add_friend(
    user_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PersonBrief:
    """«Добавить» работает сразу: подтверждения ждать не нужно.

    Взаимность появляется сама, когда добавляют в ответ, — и тогда это дружба.
    """
    try:
        relation = await social.follow(session, user.id, user_id)
    except SocialError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _person(await session.get(User, user_id), relation)


@router.delete("/users/{user_id}/friend", response_model=PersonBrief)
async def remove_friend(
    user_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PersonBrief:
    relation = await social.unfollow(session, user.id, user_id)
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return _person(target, relation)


@router.get("/users/{user_id}", response_model=ProfileOut)
async def profile(
    user_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProfileOut:
    found = await social.profile(session, user.id, user_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return ProfileOut(
        id=found.id,
        display_name=found.display_name,
        tg_username=found.tg_username,
        photo_url=found.photo_url,
        role=found.role,
        joined_at=found.joined_at,
        favourites=[_film(film) for film in found.favourites],
        marks=found.marks,
        watched=found.watched,
        ratings=found.ratings,
        average_rating=found.average_rating,
        ratings_by_score=found.ratings_by_score,
        friends=found.friends,
        is_me=found.id == user.id,
        relation_friends=bool(found.relation and found.relation.friends),
        relation_following=bool(found.relation and found.relation.following),
        relation_follower=bool(found.relation and found.relation.follower),
        recent=[_item(item) for item in found.recent],
    )
