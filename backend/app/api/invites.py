"""Коды-приглашения закрытой беты (расширение по просьбе клуба).

Коды выдают администраторы, выключает бету только главный админ: это решение
о том, кто вообще может пользоваться клубом, и оно не должно приниматься
случайным нажатием.
"""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.auth import AuthenticatedUser, RequireAdmin, RequireSuperadmin
from app.db import get_session
from app.models import InviteCode, User
from app.schemas import (
    BetaIn,
    InviteCodeOut,
    InviteeOut,
    InviteIn,
    PersonRowOut,
    RedeemIn,
)
from app.services import invites
from app.services.invites import InviteError

router = APIRouter(prefix="/api", tags=["invites"])


def _out(view: invites.CodeView) -> InviteCodeOut:
    return InviteCodeOut(
        id=view.id,
        code=view.code,
        max_activations=view.max_activations,
        used=view.used,
        left=view.left,
        note=view.note,
        created_at=view.created_at,
        created_by=view.created_by,
        created_by_name=view.created_by_name,
        invitees=[InviteeOut(user_id=uid, display_name=name) for uid, name in view.invitees],
    )


@router.post("/invites/redeem")
async def redeem(
    body: RedeemIn,
    user: AuthenticatedUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Ввод кода. Работает до получения доступа — иначе вводить его было бы негде."""
    try:
        code = await invites.redeem(session, user, body.code)
    except InviteError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"access": True, "code": code.code}


@router.get("/admin/invites", response_model=list[InviteCodeOut])
async def listing(
    admin: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[InviteCodeOut]:
    """Все коды: чей, сколько активаций осталось и кто по нему пришёл."""
    return [_out(view) for view in await invites.listing(session)]


@router.post("/admin/invites", response_model=InviteCodeOut, status_code=201)
async def create(
    body: InviteIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InviteCodeOut:
    try:
        code = await invites.create(session, admin.id, body.max_activations, body.note)
    except InviteError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _out(
        invites.CodeView(
            id=code.id,
            code=code.code,
            max_activations=code.max_activations,
            used=0,
            note=code.note,
            created_at=code.created_at,
            created_by=admin.id,
            created_by_name=admin.display_name,
            invitees=[],
        )
    )


@router.get("/admin/beta")
async def beta_state(
    admin: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict:
    waiting = (
        await session.scalar(
            sa.select(sa.func.count()).select_from(User).where(invites.waiting_clause())
        )
        or 0
    )
    return {"enabled": await invites.beta_enabled(session), "waiting": waiting}


@router.post("/admin/beta")
async def set_beta(
    body: BetaIn,
    admin: RequireSuperadmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Выключение беты открывает клуб всем, кто застрял на коде, и говорит им об этом."""
    opened = await invites.set_beta(session, admin.id, body.enabled)
    return {"enabled": body.enabled, "opened": opened}


@router.get("/admin/people", response_model=list[PersonRowOut])
async def people(
    admin: RequireSuperadmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[PersonRowOut]:
    """Все участники: по чьему коду пришёл каждый и кто этот код выдал."""
    author = aliased(User)
    rows = await session.execute(
        sa.select(User, InviteCode.code, author.display_name)
        .outerjoin(InviteCode, InviteCode.id == User.invite_code_id)
        .outerjoin(author, author.id == InviteCode.created_by)
        .order_by(User.created_at.desc())
    )
    return [
        PersonRowOut(
            id=user.id,
            display_name=user.display_name,
            tg_username=user.tg_username,
            role=user.role,
            created_at=user.created_at,
            has_access=user.access_granted_at is not None,
            invite_code=code,
            invited_by=author_name,
        )
        for user, code, author_name in rows
    ]
