"""Этап 1 — интерес (§4).

Обе кнопки независимы: можно поставить и «Желаемое», и «Ближайшее» одновременно,
веса складываются.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.db import get_session
from app.models import Film, Interest
from app.models.enums import FilmStatus, InterestKind, RevokeReason
from app.schemas import FilmBrief, InterestIn, InterestOut
from app.services.settings import SettingsService
from app.services.tmdb import TmdbError, ensure_film, poster_url

router = APIRouter(prefix="/api", tags=["interests"])


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


@router.post("/films/{film_id}/interest", response_model=InterestOut, status_code=201)
async def add_interest_by_id(
    film_id: int,
    body: InterestIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterestOut:
    return await _add(session, user.id, await _resolve_film(session, film_id, None), body.kind)


@router.post("/interests", response_model=InterestOut, status_code=201)
async def add_interest(
    body: InterestIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterestOut:
    film = await _resolve_film(session, None, body.tmdb_id)
    return await _add(session, user.id, film, body.kind)


async def _add(session: AsyncSession, user_id: int, film: Film, kind: InterestKind) -> InterestOut:
    settings = SettingsService(session)
    values = await settings.all()

    if kind == InterestKind.SOON:
        active_soon = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(Interest)
                .where(
                    Interest.user_id == user_id,
                    Interest.kind == InterestKind.SOON,
                    Interest.revoked_at.is_(None),
                )
            )
        ).scalar_one()
        limit = int(values["soon_limit_per_user"])
        if active_soon >= limit:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Лимит «Ближайших» — {limit}. Снимите отметку с другого фильма.",
            )

    film_id = film.id
    session.add(Interest(user_id=user_id, film_id=film_id, kind=kind))
    try:
        await session.commit()
    except IntegrityError:
        # Частичный уникальный индекс: отметка уже стоит. Повторное нажатие —
        # не ошибка пользователя, отдаём текущее состояние.
        await session.rollback()
        # Откат обесценивает все объекты сессии независимо от expire_on_commit,
        # поэтому film нужно перечитать, а не переиспользовать.
        film = await session.get(Film, film_id)
    return await _state(session, user_id, film, values)


@router.delete("/films/{film_id}/interest", response_model=InterestOut)
async def remove_interest(
    film_id: int,
    kind: InterestKind,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InterestOut:
    film = await _resolve_film(session, film_id, None)
    await session.execute(
        sa.update(Interest)
        .where(
            Interest.user_id == user.id,
            Interest.film_id == film_id,
            Interest.kind == kind,
            Interest.revoked_at.is_(None),
        )
        .values(revoked_at=sa.func.now(), revoke_reason=RevokeReason.MANUAL)
    )
    await session.commit()
    return await _state(session, user.id, film, await SettingsService(session).all())


async def _state(session: AsyncSession, user_id: int, film: Film, values: dict) -> InterestOut:
    rows = (
        (
            await session.execute(
                sa.select(Interest)
                .where(
                    Interest.user_id == user_id,
                    Interest.film_id == film.id,
                    Interest.revoked_at.is_(None),
                )
                .order_by(Interest.created_at)
            )
        )
        .scalars()
        .all()
    )

    expires_at = next(
        (
            row.created_at + timedelta(days=int(values["soon_ttl_days"]))
            for row in rows
            if row.kind == InterestKind.SOON
        ),
        None,
    )
    return InterestOut(
        film=FilmBrief(
            id=film.id,
            tmdb_id=film.tmdb_id,
            title_ru=film.title_ru,
            title_orig=film.title_orig,
            year=film.year,
            poster_url=poster_url(film.poster_path),
            genres=list(film.genres or []),
            my_interests=[row.kind for row in rows],
        ),
        kinds=[row.kind for row in rows],
        created_at=rows[0].created_at if rows else datetime.now(UTC),
        expires_at=expires_at,
    )


@router.get("/me/interests", response_model=list[InterestOut])
async def my_interests(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[InterestOut]:
    values = await SettingsService(session).all()
    films = (
        (
            await session.execute(
                sa.select(Film)
                .join(Interest, Interest.film_id == Film.id)
                .where(Interest.user_id == user.id, Interest.revoked_at.is_(None))
                .distinct()
                .order_by(Film.title_ru)
            )
        )
        .scalars()
        .all()
    )
    return [await _state(session, user.id, film, values) for film in films]
