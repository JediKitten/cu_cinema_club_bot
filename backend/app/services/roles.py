"""Назначение ролей (§9).

Главный админ назначает админов и модераторов, админ — только модераторов.
Понижать себя нельзя: иначе клуб может остаться без главного администратора,
и вернуть роль будет некому.
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User
from app.models.enums import UserRole


class RoleError(ValueError):
    """Причину показываем как есть."""


# Кто какие роли может выдавать (§9).
GRANTABLE: dict[UserRole, set[UserRole]] = {
    UserRole.SUPERADMIN: {UserRole.USER, UserRole.MODERATOR, UserRole.ADMIN},
    UserRole.ADMIN: {UserRole.USER, UserRole.MODERATOR},
}


async def assign(
    session: AsyncSession, actor: User, user_id: int, role: UserRole
) -> User:
    allowed = GRANTABLE.get(actor.role, set())
    if role not in allowed:
        raise RoleError("Вы не можете выдавать эту роль")

    target = await session.get(User, user_id)
    if target is None:
        raise RoleError("Пользователь не найден")

    if target.id == actor.id:
        # Иначе главный админ мог бы понизить сам себя, и вернуть роль было бы некому.
        raise RoleError("Свою роль изменить нельзя")

    if target.role == UserRole.SUPERADMIN:
        raise RoleError("Роль главного администратора меняется только в настройках сервера")

    previous = target.role
    target.role = role
    session.add(
        AuditLog(
            actor_id=actor.id,
            entity="user",
            entity_id=target.id,
            action="set_role",
            payload={"from": previous, "to": role},
        )
    )
    await session.commit()
    return target


async def team(session: AsyncSession) -> list[User]:
    """Все, у кого есть роль выше обычного участника."""
    rows = await session.execute(
        sa.select(User)
        .where(User.role != UserRole.USER)
        .order_by(User.role.desc(), User.display_name)
    )
    return list(rows.scalars())


async def search(session: AsyncSession, query: str, limit: int = 20) -> list[User]:
    """Поиск по имени или username — чтобы найти, кого назначать."""
    pattern = f"%{query.strip()}%"
    rows = await session.execute(
        sa.select(User)
        .where(
            User.is_active,
            sa.or_(User.display_name.ilike(pattern), User.tg_username.ilike(pattern)),
        )
        .order_by(User.display_name)
        .limit(limit)
    )
    return list(rows.scalars())
