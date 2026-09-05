"""Этап 1 — интерес (§4, с уточнением клуба).

Относительно каждого фильма у пользователя ровно одно из трёх состояний:
ничего, «Желаемое», «Ближайшее». Кнопки взаимоисключающие. «Просмотрено»
живёт отдельно и отметке не мешает.
"""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.db import get_session
from app.models import Film, Interest
from app.models.enums import FilmStatus, InterestKind
from app.schemas import FilmBrief, InterestIn, InterestOut
from app.services import interests as marks
from app.services.interests import InterestError, MarkState
from app.services.settings import SettingsService
from app.services.tmdb import TmdbError, ensure_film, poster_url

router = APIRouter(prefix="/api", tags=["interests"])


class WatchedIn(BaseModel):
    watched: bool = True
    # Фильма может ещё не быть в каталоге: он попадёт туда по этому id,
    # ровно как при первой отметке интереса.
    tmdb_id: int | None = None


async def _resolve_film(session: AsyncSession, film_id: int | None, tmdb_id: int | None) -> Film:
    """Фильм из TMDB попадает в каталог именно здесь — в момент первой отметки."""
    if film_id is not None:
        film = await session.get(Film, film_id)
        if film is None or film.status == FilmStatus.HIDDEN:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Фильм не найден")
        return film
    if tmdb_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен film_id или tmdb_id")
    try:
        return await ensure_film(session, tmdb_id)
    except TmdbError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"TMDB недоступен: {exc}") from exc


def brief(film: Film, mark: MarkState) -> FilmBrief:
    return FilmBrief(
        id=film.id,
        tmdb_id=film.tmdb_id,
        title_ru=film.title_ru,
        title_orig=film.title_orig,
        year=film.year,
        poster_url=poster_url(film.poster_path),
        genres=list(film.genres or []),
        directors=list(film.directors or []),
        my_interests=[mark.effective_kind] if mark.effective_kind else [],
        can_renew_soon=mark.can_renew_soon,
        soon_expires_at=mark.expires_at,
        watched=mark.watched,
    )


def _out(film: Film, mark: MarkState) -> InterestOut:
    return InterestOut(
        film=brief(film, mark),
        kinds=[mark.effective_kind] if mark.effective_kind else [],
        expires_at=mark.expires_at,
        can_renew_soon=mark.can_renew_soon,
        watched=mark.watched,
    )


async def _ttl(session: AsyncSession) -> int:
    return int(await SettingsService(session).get("soon_ttl_days"))


@router.post("/films/{film_id}/interest", response_model=InterestOut, status_code=201)
async def add_interest_by_id(
    film_id: int,
    body: InterestIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterestOut:
    film = await _resolve_film(session, film_id, None)
    return await _set(session, user.id, film, body.kind)


@router.post("/interests", response_model=InterestOut, status_code=201)
async def add_interest(
    body: InterestIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterestOut:
    film = await _resolve_film(session, None, body.tmdb_id)
    return await _set(session, user.id, film, body.kind)


async def _set(
    session: AsyncSession, user_id: int, film: Film, kind: InterestKind
) -> InterestOut:
    values = await SettingsService(session).all()
    try:
        mark = await marks.set_mark(
            session,
            user_id,
            film.id,
            kind,
            soon_ttl_days=int(values["soon_ttl_days"]),
            soon_limit=int(values["soon_limit_per_user"]),
        )
    except InterestError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _out(film, mark)


@router.delete("/films/{film_id}/interest", response_model=InterestOut)
async def remove_interest(
    film_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterestOut:
    """Снимает отметку любого вида: состояние одно, выбирать нечего."""
    film = await _resolve_film(session, film_id, None)
    mark = await marks.clear_mark(session, user.id, film_id, await _ttl(session))
    return _out(film, mark)


@router.post("/watched", response_model=InterestOut)
async def set_watched_by_tmdb(
    body: WatchedIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterestOut:
    """«Просмотрено» для фильма, которого ещё нет в каталоге.

    Отдельный маршрут, потому что id ещё не существует: фильм заводится здесь,
    как и при первой отметке интереса.
    """
    film = await _resolve_film(session, None, body.tmdb_id)
    mark = await marks.set_watched(session, user.id, film.id, body.watched, await _ttl(session))
    return _out(film, mark)


@router.post("/films/{film_id}/watched", response_model=InterestOut)
async def set_watched(
    film_id: int,
    body: WatchedIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterestOut:
    film = await _resolve_film(session, film_id, None)
    mark = await marks.set_watched(
        session, user.id, film_id, body.watched, await _ttl(session)
    )
    return _out(film, mark)


@router.get("/me/interests", response_model=list[InterestOut])
async def my_interests(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[InterestOut]:
    ttl = await _ttl(session)
    films = (
        (
            await session.execute(
                sa.select(Film)
                .join(Interest, Interest.film_id == Film.id)
                .where(Interest.user_id == user.id, Interest.revoked_at.is_(None))
                .order_by(Film.title_ru)
            )
        )
        .scalars()
        .all()
    )
    states = await marks.marks_for_films(session, user.id, [f.id for f in films], ttl)
    return [_out(film, states[film.id]) for film in films]
