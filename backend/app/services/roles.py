"""Назначение ролей (§9).

Главный админ назначает админов и модераторов, админ — только модераторов.
Понижать себя нельзя: иначе клуб может остаться без главного администратора,
и вернуть роль будет некому. Равного себе тоже трогать нельзя — иначе два
администратора могли бы разжаловать друг друга, и побеждал бы тот, кто успел.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User
from app.models.enums import NotificationKind, UserRole
from app.services import notify


class RoleError(ValueError):
    """Причину показываем как есть."""


# Кто какие роли может выдавать (§9).
GRANTABLE: dict[UserRole, set[UserRole]] = {
    UserRole.SUPERADMIN: {UserRole.USER, UserRole.MODERATOR, UserRole.ADMIN},
    UserRole.ADMIN: {UserRole.USER, UserRole.MODERATOR},
}

TITLE: dict[UserRole, str] = {
    UserRole.USER: "участник",
    UserRole.MODERATOR: "модератор",
    UserRole.ADMIN: "администратор",
    UserRole.SUPERADMIN: "главный администратор",
}

# Что человек получил вместе с ролью. Здесь, а не в шаблоне уведомления:
# права описаны в одном месте с правилами их выдачи.
ABILITIES: dict[UserRole, str] = {
    UserRole.MODERATOR: (
        "Вам доступна вкладка «Клуб»: заявки на фильмы, отметка присутствия "
        "и список пришедших."
    ),
    UserRole.ADMIN: (
        "Вам доступна вкладка «Клуб»: шорт-лист недели, расстановка показов "
        "и публикация расписания, свои события в обход алгоритма, "
        "аналитика и назначение модераторов."
    ),
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

    if target.role.rank >= actor.role.rank:
        # Админ не трогает другого админа: иначе разжалование превращалось бы
        # в гонку, где прав тот, кто нажал первым.
        raise RoleError("Нельзя менять роль равного вам по правам")

    if target.role == role:
        raise RoleError(f"У этого человека уже роль «{TITLE[role]}»")

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
    await notify.queue(
        session,
        target.id,
        NotificationKind.ROLE_GRANTED,
        # Метка времени в ключе: роль могут выдать, снять и выдать снова —
        # каждый раз это отдельная новость, а не повтор прежней.
        dedup_key=f"role:{target.id}:{role}:{datetime.now(UTC).isoformat(timespec='seconds')}",
        payload={
            "role_title": TITLE[role],
            "abilities": ABILITIES.get(role),
            "demoted": role.rank < previous.rank,
        },
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
