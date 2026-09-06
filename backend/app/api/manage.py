"""Управление клубом: ручные события и роли (§9, §10)."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import RequireAdmin, RequireSuperadmin
from app.db import get_session
from app.models import Confirmation, Film, Screening, Slot
from app.models.enums import ConfirmationState, UserRole
from app.schemas import (
    CancelEventIn,
    EventIn,
    EventOut,
    EventPatch,
    FilmBrief,
    RevealIn,
    RoleIn,
    TeamMember,
)
from app.services import events as events_service
from app.services import roles as roles_service
from app.services import schedule as schedule_service
from app.services.events import EventError
from app.services.roles import RoleError
from app.services.tmdb import poster_url

router = APIRouter(prefix="/api/admin", tags=["manage"])


@router.post("/events", status_code=201)
async def create_event(
    body: EventIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Событие в обход алгоритма: любое время, фильм необязателен."""
    try:
        event = await events_service.create(
            session,
            starts_at=body.starts_at,
            actor_id=admin.id,
            film_id=body.film_id,
            title=body.title,
            note=body.note,
            duration_min=body.duration_min,
        )
    except EventError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"id": event.id, "starts_at": body.starts_at.isoformat()}


async def _event_out(session: AsyncSession, event: Screening) -> EventOut:
    slot = await session.get(Slot, event.slot_id)
    film = await session.get(Film, event.film_id) if event.film_id else None
    confirmed = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Confirmation)
        .where(
            Confirmation.screening_id == event.id,
            Confirmation.state == ConfirmationState.CONFIRMED,
        )
    )
    return EventOut(
        id=event.id,
        starts_at=slot.starts_at,
        duration_min=slot.duration_min,
        film_id=event.film_id,
        film=(
            FilmBrief(
                id=film.id,
                tmdb_id=film.tmdb_id,
                title_ru=film.title_ru,
                title_orig=film.title_orig,
                year=film.year,
                poster_url=poster_url(film.poster_path),
                genres=list(film.genres or []),
                directors=list(film.directors or []),
            )
            if film
            else None
        ),
        title=event.title,
        note=event.note,
        confirmed=confirmed or 0,
    )


@router.get("/events", response_model=list[EventOut])
async def list_events(
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[EventOut]:
    """Будущие события вне цикла — их и правят."""
    return [await _event_out(session, event) for event in await events_service.upcoming(session)]


@router.patch("/events/{event_id}", response_model=EventOut)
async def edit_event(
    event_id: int,
    body: EventPatch,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    """Правка уже назначенного события.

    Меняется только присланное: `exclude_unset` отличает «не трогать поле»
    от «очистить его», и без этого снять фильм с анонса было бы нельзя.
    """
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нечего менять")
    try:
        event = await events_service.update(session, event_id, admin.id, changes)
    except EventError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _event_out(session, event)


@router.post("/events/{event_id}/cancel", response_model=EventOut)
async def cancel_event(
    event_id: int,
    body: CancelEventIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventOut:
    """Отмена события. Комментарий уходит всем, кто собирался прийти (§7)."""
    event = await session.get(Screening, event_id)
    if event is None or not event.is_manual:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    try:
        cancelled = await schedule_service.cancel_screening(
            session, event_id, body.reason, admin.id
        )
    except schedule_service.ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _event_out(session, cancelled)


@router.post("/events/{event_id}/reveal")
async def reveal_event(
    event_id: int,
    body: RevealIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Объявляет фильм у события, анонсированного заранее."""
    try:
        event = await events_service.reveal(session, event_id, body.film_id, admin.id)
    except EventError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"id": event.id, "film_id": event.film_id}


@router.get("/team", response_model=list[TeamMember])
async def team(
    admin: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[TeamMember]:
    members = await roles_service.team(session)
    return [TeamMember.model_validate(m, from_attributes=True) for m in members]


@router.get("/users", response_model=list[TeamMember])
async def find_users(
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=1, max_length=100)],
) -> list[TeamMember]:
    """Поиск, чтобы найти, кого назначать."""
    found = await roles_service.search(session, q)
    return [TeamMember.model_validate(m, from_attributes=True) for m in found]


@router.put("/users/{user_id}/role", response_model=TeamMember)
async def set_role(
    user_id: int,
    body: RoleIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TeamMember:
    """Админ назначает модераторов, главный админ — ещё и админов (§9)."""
    try:
        updated = await roles_service.assign(session, admin, user_id, body.role)
    except RoleError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return TeamMember.model_validate(updated, from_attributes=True)


@router.get("/roles", response_model=list[UserRole])
async def grantable_roles(admin: RequireAdmin) -> list[UserRole]:
    """Какие роли этот администратор вправе выдавать."""
    return sorted(roles_service.GRANTABLE.get(admin.role, set()), key=lambda r: r.rank)


@router.get("/whoami")
async def whoami(admin: RequireSuperadmin) -> dict:
    """Проверка, что вызывающий — главный админ: интерфейс по ней решает,
    показывать ли панель параметров."""
    return {"role": admin.role}
