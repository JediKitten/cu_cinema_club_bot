"""Пригласительные ссылки на конкретный фильм.

Смысл: человек зовёт друзей посмотреть именно этот фильм. Голос за него
НЕ ставится автоматически — приглашённый видит карточку и решает сам, одним
нажатием. Иначе накрутить вес фильма было бы вопросом рассылки ссылки в чат,
и шорт-лист отражал бы активность одного человека, а не интерес клуба.
"""

import re
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Film, Interest, Referral, User

# Формат полезной нагрузки Telegram: только латиница, цифры, «_» и «-»,
# не длиннее 64 символов. «f12r7» — фильм 12, позвал пользователь 7.
PAYLOAD = re.compile(r"^f(\d+)r(\d+)$")


class ReferralError(ValueError):
    pass


def make_payload(film_id: int, referrer_id: int) -> str:
    return f"f{film_id}r{referrer_id}"


def parse_payload(payload: str) -> tuple[int, int] | None:
    match = PAYLOAD.match((payload or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def invite_link(bot_username: str, film_id: int, referrer_id: int) -> str:
    return f"https://t.me/{bot_username}?start={make_payload(film_id, referrer_id)}"


async def record(
    session: AsyncSession, referrer_id: int, invitee_id: int, film_id: int
) -> bool:
    """Запоминает переход. Возвращает True, если приглашение засчитано новым.

    Себя пригласить нельзя, повторный переход не создаёт второй записи:
    иначе счётчик приглашённых накручивался бы собственными кликами.
    """
    if referrer_id == invitee_id:
        return False
    if await session.get(User, referrer_id) is None:
        return False
    if await session.get(Film, film_id) is None:
        return False

    stmt = (
        insert(Referral)
        .values(referrer_id=referrer_id, invitee_id=invitee_id, film_id=film_id)
        .on_conflict_do_nothing(index_elements=[Referral.invitee_id, Referral.film_id])
        .returning(Referral.id)
    )
    created = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()
    return created is not None


@dataclass(slots=True)
class Stats:
    invited: int
    accepted: int


async def stats(session: AsyncSession, referrer_id: int) -> Stats:
    """Сколько человек перешло по ссылкам и сколько из них отметило фильм.

    «Согласился» считается по отметке, поставленной ПОСЛЕ перехода: если
    человек уже держал этот фильм в списках, приглашение ни при чём.
    """
    invited = (
        await session.scalar(
            sa.select(sa.func.count()).select_from(Referral).where(
                Referral.referrer_id == referrer_id
            )
        )
        or 0
    )
    accepted = (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Referral)
            .join(
                Interest,
                sa.and_(
                    Interest.user_id == Referral.invitee_id,
                    Interest.film_id == Referral.film_id,
                    Interest.revoked_at.is_(None),
                    Interest.created_at >= Referral.created_at,
                ),
            )
            .where(Referral.referrer_id == referrer_id)
        )
        or 0
    )
    return Stats(invited=invited, accepted=accepted)


async def pending_invite(
    session: AsyncSession, invitee_id: int, film_id: int
) -> User | None:
    """Кто позвал этого человека на этот фильм — для подписи в карточке."""
    referral = (
        await session.execute(
            sa.select(Referral).where(
                Referral.invitee_id == invitee_id, Referral.film_id == film_id
            )
        )
    ).scalar_one_or_none()
    if referral is None:
        return None
    return await session.get(User, referral.referrer_id)
