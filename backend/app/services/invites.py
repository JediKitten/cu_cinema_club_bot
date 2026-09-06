"""Коды-приглашения на время закрытого бета-теста (расширение по просьбе клуба).

Пока бета включена, доступ к боту и приложению получает только тот, кто ввёл
код. Коды выдают администраторы, у каждого — своё число активаций.

Учёт устроен без отдельной таблицы активаций: пришедший помечается в
`users.invite_code_id`, и «сколько осталось» выводится из того же поля. Счётчик,
который нельзя рассинхронизировать со списком приглашённых, — тот, которого нет.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import AuditLog, InviteCode, User
from app.models.enums import NotificationKind, UserRole
from app.services import notify
from app.services.settings import SettingsService

# Без похожих друг на друга символов: код диктуют вслух и переписывают с экрана,
# и «0 или O» — самая частая причина, по которой он «не подходит».
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LENGTH = 6

SETTING = "beta_invite_required"

# Ответ, по которому приложение понимает, что надо показать экран кода,
# а не общую ошибку доступа.
NEED_CODE = "Нужен код-приглашение"


class InviteError(ValueError):
    """Причину показываем как есть."""


def normalize(raw: str) -> str:
    """Пробелы, дефисы и регистр значения не имеют: человек вводит код руками."""
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())


def generate() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


async def beta_enabled(session: AsyncSession) -> bool:
    return bool(await SettingsService(session).get(SETTING))


def waiting_clause():
    """Кто действительно стоит за дверью.

    Не всякий без отметки о доступе ждёт кода: у администраторов её и не
    появляется — их пускают по роли. Прислать им «клуб теперь открыт» значило бы
    сообщить новость тем, кто её и создал.
    """
    return sa.and_(
        User.access_granted_at.is_(None),
        User.tg_id.is_not(None),
        User.role == UserRole.USER,
    )


def has_access(user: User, beta: bool) -> bool:
    """Пускаем без кода тех, у кого он и не должен спрашиваться.

    Роль выше участника — это админ или модератор клуба: запирать их за кодом
    значило бы запереть и тех, кто коды выдаёт.
    """
    return not beta or user.access_granted_at is not None or user.role != UserRole.USER


async def _add_one(
    session: AsyncSession, actor_id: int, max_activations: int, note: str | None
) -> InviteCode:
    """Одна запись с уникальным кодом.

    Совпадение маловероятно, но не невозможно, поэтому полагаемся на уникальный
    индекс, а не на проверку перед вставкой: между ними всё равно есть щель.
    Вставка идёт во вложенной транзакции — иначе конфликт одного кода отменил бы
    всю пачку.
    """
    for _ in range(5):
        code = InviteCode(
            code=generate(),
            created_by=actor_id,
            max_activations=max_activations,
            note=(note or "").strip() or None,
        )
        try:
            async with session.begin_nested():
                session.add(code)
                await session.flush()
        except IntegrityError:
            continue
        return code
    raise InviteError("Не удалось выдать код, попробуйте ещё раз")


async def create_many(
    session: AsyncSession,
    actor_id: int,
    count: int,
    max_activations: int,
    note: str | None = None,
) -> list[InviteCode]:
    """Пачка кодов: `count` штук, у каждого по `max_activations` активаций.

    Один код на группу и по коду на человека — разные задачи: первый экономит
    переписку, второй отвечает на вопрос «кто именно вошёл». Поэтому оба числа
    задаются отдельно.
    """
    if count < 1:
        raise InviteError("Кодов должно быть хотя бы один")
    if max_activations < 1:
        raise InviteError("Активаций должно быть хотя бы одна")

    codes = [await _add_one(session, actor_id, max_activations, note) for _ in range(count)]
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="invite_code",
            action="create",
            payload={
                "codes": [code.code for code in codes],
                "max_activations": max_activations,
            },
        )
    )
    await session.commit()
    return codes


async def create(
    session: AsyncSession, actor_id: int, max_activations: int, note: str | None = None
) -> InviteCode:
    """Один код — частный случай пачки."""
    return (await create_many(session, actor_id, 1, max_activations, note))[0]


@dataclass(slots=True)
class CodeView:
    id: int
    code: str
    max_activations: int
    used: int
    note: str | None
    created_at: datetime
    created_by: int
    created_by_name: str
    invitees: list[tuple[int, str]]

    @property
    def left(self) -> int:
        return max(0, self.max_activations - self.used)


async def listing(session: AsyncSession) -> list[CodeView]:
    """Все коды с остатком активаций и теми, кто по ним пришёл."""
    author = aliased(User)
    rows = (
        await session.execute(
            sa.select(InviteCode, author.display_name)
            .join(author, author.id == InviteCode.created_by)
            .order_by(InviteCode.created_at.desc())
        )
    ).all()

    invitees: dict[int, list[tuple[int, str]]] = {}
    for user_id, name, code_id in await session.execute(
        sa.select(User.id, User.display_name, User.invite_code_id)
        .where(User.invite_code_id.is_not(None))
        .order_by(User.access_granted_at)
    ):
        invitees.setdefault(code_id, []).append((user_id, name))

    return [
        CodeView(
            id=code.id,
            code=code.code,
            max_activations=code.max_activations,
            used=len(invitees.get(code.id, [])),
            note=code.note,
            created_at=code.created_at,
            created_by=code.created_by,
            created_by_name=author_name,
            invitees=invitees.get(code.id, []),
        )
        for code, author_name in rows
    ]


async def redeem(session: AsyncSession, user: User, raw: str) -> InviteCode:
    """Активация кода. Возвращает код или падает с понятной причиной."""
    if user.access_granted_at is not None:
        raise InviteError("Доступ у вас уже есть")

    value = normalize(raw)
    if not value:
        raise InviteError("Введите код")

    code = (
        await session.execute(sa.select(InviteCode).where(InviteCode.code == value))
    ).scalar_one_or_none()
    if code is None or code.revoked_at is not None:
        raise InviteError("Такого кода нет")

    used = (
        await session.scalar(
            sa.select(sa.func.count()).select_from(User).where(User.invite_code_id == code.id)
        )
        or 0
    )
    if used >= code.max_activations:
        raise InviteError("Этот код уже разобрали")

    user.access_granted_at = datetime.now(UTC)
    user.invite_code_id = code.id
    session.add(
        AuditLog(
            actor_id=user.id,
            entity="invite_code",
            entity_id=code.id,
            action="redeem",
        )
    )
    await session.commit()
    return code


async def set_beta(session: AsyncSession, actor_id: int, enabled: bool) -> int:
    """Включает или выключает вход по кодам.

    При выключении доступ получают все, кто успел прийти и застрял на коде,
    и каждому уходит уведомление: человек, которого не пустили, сам проверять
    не станет. Возвращает, скольким открыли.
    """
    await SettingsService(session).set_many({SETTING: enabled}, actor_id)
    session.add(
        AuditLog(actor_id=actor_id, entity="settings", action="beta", payload={"enabled": enabled})
    )

    opened = 0
    if not enabled:
        waiting = (
            (await session.execute(sa.select(User).where(waiting_clause()))).scalars().all()
        )
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        for user in waiting:
            user.access_granted_at = datetime.now(UTC)
            # Знакомство им ещё не показывали — за кодом до него не доходило.
            # Обнуляем явно, чтобы первый же /start показал именно его.
            user.onboarded_at = None
            await notify.queue(
                session,
                user.id,
                NotificationKind.BETA_OPENED,
                dedup_key=f"beta_opened:{user.id}:{stamp}",
            )
            opened += 1

    await session.commit()
    return opened
