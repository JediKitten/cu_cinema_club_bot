"""Управление клубом: ручные события и роли (§9, §10)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import RequireAdmin, RequireSuperadmin
from app.db import get_session
from app.models.enums import UserRole
from app.schemas import EventIn, RevealIn, RoleIn, TeamMember
from app.services import events as events_service
from app.services import roles as roles_service
from app.services.events import EventError
from app.services.roles import RoleError

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
