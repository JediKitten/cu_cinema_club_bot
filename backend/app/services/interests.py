"""Отметки интереса — переключение состояний (§4, с уточнением клуба).

У пользователя относительно фильма ровно одно из трёх состояний:
ничего, «Желаемое» или «Ближайшее». Кнопки взаимоисключающие: нажатие одной
снимает другую. «Просмотрено» стоит особняком и ни на что из этого не влияет —
посмотренный фильм можно оставить в «Желаемом», чтобы сходить снова.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Interest, Watch
from app.models.enums import InterestKind, RevokeReason


class InterestError(ValueError):
    """Причину показываем пользователю как есть."""


@dataclass(frozen=True, slots=True)
class MarkState:
    """Состояние пользователя по фильму — то, что рисует интерфейс."""

    kind: InterestKind | None
    # Что отметка представляет собой сейчас: истёкшее «Ближайшее» уже работает
    # как «Желаемое», и показывать его надо именно так.
    effective_kind: InterestKind | None
    expires_at: datetime | None
    # Истекло — предлагаем поставить «Ближайшее» заново (§4).
    can_renew_soon: bool
    watched: bool


async def active_interest(
    session: AsyncSession, user_id: int, film_id: int
) -> Interest | None:
    return (
        await session.execute(
            sa.select(Interest).where(
                Interest.user_id == user_id,
                Interest.film_id == film_id,
                Interest.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def state(
    session: AsyncSession, user_id: int, film_id: int, soon_ttl_days: int
) -> MarkState:
    interest = await active_interest(session, user_id, film_id)
    watched = bool(
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Watch)
            .where(Watch.user_id == user_id, Watch.film_id == film_id)
        )
    )
    if interest is None:
        return MarkState(None, None, None, can_renew_soon=False, watched=watched)

    expires_at = None
    effective = interest.kind
    renew = False
    if interest.kind == InterestKind.SOON:
        expires_at = interest.created_at + timedelta(days=soon_ttl_days)
        if expires_at <= datetime.now(UTC):
            # Срок вышел: вес уже считается как у «Желаемого», значит и показывать
            # надо «Желаемое», предложив продлить.
            effective = InterestKind.WISHLIST
            renew = True

    return MarkState(
        kind=interest.kind,
        effective_kind=effective,
        expires_at=expires_at,
        can_renew_soon=renew,
        watched=watched,
    )


async def set_mark(
    session: AsyncSession,
    user_id: int,
    film_id: int,
    kind: InterestKind,
    soon_ttl_days: int,
    soon_limit: int,
) -> MarkState:
    """Ставит отметку, снимая противоположную. Идемпотентна."""
    current = await active_interest(session, user_id, film_id)

    if current is not None and current.kind == kind:
        # Та же кнопка. Для просроченного «Ближайшего» это продление —
        # ставим отметку заново, чтобы срок пошёл с сегодняшнего дня.
        expired = kind == InterestKind.SOON and current.created_at + timedelta(
            days=soon_ttl_days
        ) <= datetime.now(UTC)
        if not expired:
            return await state(session, user_id, film_id, soon_ttl_days)

    if kind == InterestKind.SOON:
        await _check_soon_limit(session, user_id, film_id, soon_limit)

    if current is not None:
        current.revoked_at = sa.func.now()
        current.revoke_reason = RevokeReason.SUPERSEDED
        # Снимаем до вставки: иначе частичный уникальный индекс не пустит.
        await session.flush()

    session.add(Interest(user_id=user_id, film_id=film_id, kind=kind))
    await session.commit()
    return await state(session, user_id, film_id, soon_ttl_days)


async def _check_soon_limit(
    session: AsyncSession, user_id: int, film_id: int, soon_limit: int
) -> None:
    """Лимит считаем по действующим «Ближайшим» (§4).

    Просроченные не в счёт: они уже ведут себя как «Желаемое» и место не занимают.
    """
    from app.services.settings import SettingsService  # локально: избегаем цикла

    ttl = int(await SettingsService(session).get("soon_ttl_days"))
    cutoff = datetime.now(UTC) - timedelta(days=ttl)

    active = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Interest)
        .where(
            Interest.user_id == user_id,
            Interest.film_id != film_id,
            Interest.kind == InterestKind.SOON,
            Interest.revoked_at.is_(None),
            Interest.created_at > cutoff,
        )
    )
    if (active or 0) >= soon_limit:
        raise InterestError(
            f"Лимит «Ближайших» — {soon_limit}. Снимите отметку с другого фильма."
        )


async def clear_mark(
    session: AsyncSession, user_id: int, film_id: int, soon_ttl_days: int
) -> MarkState:
    await session.execute(
        sa.update(Interest)
        .where(
            Interest.user_id == user_id,
            Interest.film_id == film_id,
            Interest.revoked_at.is_(None),
        )
        .values(revoked_at=sa.func.now(), revoke_reason=RevokeReason.MANUAL)
    )
    await session.commit()
    return await state(session, user_id, film_id, soon_ttl_days)


async def set_watched(
    session: AsyncSession, user_id: int, film_id: int, watched: bool, soon_ttl_days: int
) -> MarkState:
    """«Просмотрено» не трогает отметки: хотеть пересмотреть — нормально."""
    if watched:
        exists = await session.scalar(
            sa.select(Watch.id).where(Watch.user_id == user_id, Watch.film_id == film_id)
        )
        if exists is None:
            session.add(Watch(user_id=user_id, film_id=film_id, source="manual"))
    else:
        await session.execute(
            sa.delete(Watch).where(Watch.user_id == user_id, Watch.film_id == film_id)
        )
    await session.commit()
    return await state(session, user_id, film_id, soon_ttl_days)


async def marks_for_films(
    session: AsyncSession, user_id: int, film_ids: list[int], soon_ttl_days: int
) -> dict[int, MarkState]:
    """Состояния пачкой — для списков, чтобы не ходить в базу на каждую строку."""
    if not film_ids:
        return {}

    interests = (
        (
            await session.execute(
                sa.select(Interest).where(
                    Interest.user_id == user_id,
                    Interest.film_id.in_(film_ids),
                    Interest.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    watched = set(
        (
            await session.execute(
                sa.select(Watch.film_id).where(
                    Watch.user_id == user_id, Watch.film_id.in_(film_ids)
                )
            )
        )
        .scalars()
        .all()
    )

    now = datetime.now(UTC)
    result: dict[int, MarkState] = {}
    by_film = {interest.film_id: interest for interest in interests}

    for film_id in film_ids:
        interest = by_film.get(film_id)
        if interest is None:
            result[film_id] = MarkState(None, None, None, False, film_id in watched)
            continue

        expires_at = None
        effective = interest.kind
        renew = False
        if interest.kind == InterestKind.SOON:
            expires_at = interest.created_at + timedelta(days=soon_ttl_days)
            if expires_at <= now:
                effective = InterestKind.WISHLIST
                renew = True

        result[film_id] = MarkState(
            kind=interest.kind,
            effective_kind=effective,
            expires_at=expires_at,
            can_renew_soon=renew,
            watched=film_id in watched,
        )
    return result
