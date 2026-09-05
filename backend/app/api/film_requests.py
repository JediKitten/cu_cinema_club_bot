"""Заявки «не нашёл фильм» (§4)."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireAdmin
from app.db import get_session
from app.models import FilmRequest
from app.models.enums import FilmRequestStatus, NotificationKind
from app.schemas import FilmRequestIn, FilmRequestOut
from app.services import notify
from app.services.tmdb import TmdbError, ensure_film

router = APIRouter(prefix="/api", tags=["film-requests"])


class ResolveIn(BaseModel):
    approve: bool
    tmdb_id: int | None = None
    comment: str | None = None


@router.post("/film-requests", response_model=FilmRequestOut, status_code=201)
async def create_request(
    body: FilmRequestIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FilmRequestOut:
    request = FilmRequest(user_id=user.id, **body.model_dump())
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return FilmRequestOut.model_validate(request, from_attributes=True)


@router.get("/me/film-requests", response_model=list[FilmRequestOut])
async def my_requests(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[FilmRequestOut]:
    rows = (
        await session.execute(
            sa.select(FilmRequest)
            .where(FilmRequest.user_id == user.id)
            .order_by(FilmRequest.created_at.desc())
        )
    ).scalars()
    return [FilmRequestOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/admin/film-requests", response_model=list[FilmRequestOut])
async def pending_requests(
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: FilmRequestStatus = FilmRequestStatus.PENDING,
) -> list[FilmRequestOut]:
    rows = (
        await session.execute(
            sa.select(FilmRequest)
            .where(FilmRequest.status == status_filter)
            .order_by(FilmRequest.created_at)
        )
    ).scalars()
    return [FilmRequestOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/admin/film-requests/{request_id}", response_model=FilmRequestOut)
async def resolve_request(
    request_id: int,
    body: ResolveIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FilmRequestOut:
    request = await session.get(FilmRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заявка не найдена")
    if request.status != FilmRequestStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Заявка уже обработана")

    if body.approve:
        if body.tmdb_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для одобрения нужен tmdb_id фильма")
        try:
            film = await ensure_film(session, body.tmdb_id)
        except TmdbError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        request.resolved_film_id = film.id
        request.status = FilmRequestStatus.APPROVED
    else:
        request.status = FilmRequestStatus.REJECTED

    request.resolved_by = admin.id
    request.resolution_comment = body.comment
    request.resolved_at = sa.func.now()

    # Автора заявки уведомляем о результате (§4).
    await notify.queue(
        session,
        request.user_id,
        NotificationKind.FILM_REQUEST_RESOLVED,
        dedup_key=f"film_request:{request.id}",
        payload={
            "request_id": request.id,
            "approved": body.approve,
            "comment": body.comment,
            "film_id": request.resolved_film_id,
        },
    )
    await session.commit()
    await session.refresh(request)
    return FilmRequestOut.model_validate(request, from_attributes=True)
