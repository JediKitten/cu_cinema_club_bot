"""Три состояния отметки и их переходы (§4, с уточнением клуба).

У пользователя относительно фильма ровно одно из: ничего, «Желаемое»,
«Ближайшее». «Просмотрено» — отдельно и ни на что не влияет.
"""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Interest, Watch
from app.models.enums import InterestKind, RevokeReason
from app.services import interests as marks
from app.services.interests import InterestError
from app.services.weights import WeightParams, interest_weight_expr
from tests.test_weights import make_film, make_user

TTL = 14
LIMIT = 10

PARAMS = WeightParams(
    wishlist_base_weight=1.0,
    wishlist_half_life_days=180.0,
    wishlist_weight_floor=0.2,
    soon_weight=3.0,
    soon_ttl_days=TTL,
)


async def pair(session):
    user = await make_user(session, "Зритель")
    film = await make_film(session, "Фильм")
    await session.commit()
    return user, film


async def set_age(session, interest_id: int, days: float) -> None:
    """Состаривает отметку, не трогая остальное."""
    await session.execute(
        sa.update(Interest)
        .where(Interest.id == interest_id)
        .values(created_at=datetime.now(UTC) - timedelta(days=days))
    )
    await session.commit()


async def active(session, user_id: int, film_id: int) -> Interest | None:
    return await marks.active_interest(session, user_id, film_id)


async def test_starts_with_nothing(session):
    user, film = await pair(session)
    state = await marks.state(session, user.id, film.id, TTL)
    assert state.kind is None
    assert state.effective_kind is None
    assert state.watched is False


async def test_second_button_replaces_the_first(session):
    """Оба состояния одновременно невозможны."""
    user, film = await pair(session)

    await marks.set_mark(session, user.id, film.id, InterestKind.WISHLIST, TTL, LIMIT)
    state = await marks.set_mark(session, user.id, film.id, InterestKind.SOON, TTL, LIMIT)

    assert state.effective_kind == InterestKind.SOON

    rows = (
        (await session.execute(sa.select(Interest).where(Interest.film_id == film.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    alive = [r for r in rows if r.revoked_at is None]
    assert len(alive) == 1 and alive[0].kind == InterestKind.SOON

    dropped = next(r for r in rows if r.revoked_at is not None)
    assert dropped.kind == InterestKind.WISHLIST
    assert dropped.revoke_reason == RevokeReason.SUPERSEDED


async def test_pressing_the_same_button_changes_nothing(session):
    user, film = await pair(session)
    await marks.set_mark(session, user.id, film.id, InterestKind.WISHLIST, TTL, LIMIT)
    await marks.set_mark(session, user.id, film.id, InterestKind.WISHLIST, TTL, LIMIT)

    total = await session.scalar(sa.select(sa.func.count()).select_from(Interest))
    assert total == 1


async def test_clear_removes_any_kind(session):
    user, film = await pair(session)
    await marks.set_mark(session, user.id, film.id, InterestKind.SOON, TTL, LIMIT)

    state = await marks.clear_mark(session, user.id, film.id, TTL)
    assert state.effective_kind is None
    assert await active(session, user.id, film.id) is None


async def test_expired_soon_becomes_wishlist_without_any_cron(session):
    """Через две недели «Ближайшее» само превращается в «Желаемое» (§4)."""
    user, film = await pair(session)
    await marks.set_mark(session, user.id, film.id, InterestKind.SOON, TTL, LIMIT)
    interest = await active(session, user.id, film.id)
    await set_age(session, interest.id, TTL + 1)

    state = await marks.state(session, user.id, film.id, TTL)
    assert state.kind == InterestKind.SOON  # в базе запись не менялась
    assert state.effective_kind == InterestKind.WISHLIST  # а ведёт себя как «Желаемое»
    assert state.can_renew_soon is True


async def test_weight_drops_from_three_to_one_at_expiry(session):
    """Вес 3 держится весь срок, затем становится базовым и дальше затухает."""
    user, film = await pair(session)
    await marks.set_mark(session, user.id, film.id, InterestKind.SOON, TTL, LIMIT)
    interest = await active(session, user.id, film.id)

    async def weight() -> float:
        return float(
            await session.scalar(
                sa.select(interest_weight_expr(PARAMS)).where(Interest.id == interest.id)
            )
        )

    await set_age(session, interest.id, TTL - 1)
    assert await weight() == pytest.approx(3.0)

    # Сразу после истечения — ровно базовый вес, а не половина от него:
    # затухание отсчитывается от момента истечения, а не от постановки отметки.
    await set_age(session, interest.id, TTL)
    assert await weight() == pytest.approx(1.0, rel=1e-3)

    # Ещё через период полураспада — половина.
    await set_age(session, interest.id, TTL + 180)
    assert await weight() == pytest.approx(0.5, rel=1e-3)

    # И никогда ниже порога.
    await set_age(session, interest.id, TTL + 10_000)
    assert await weight() == pytest.approx(PARAMS.wishlist_weight_floor)


async def test_renewing_expired_soon_restarts_the_term(session):
    user, film = await pair(session)
    await marks.set_mark(session, user.id, film.id, InterestKind.SOON, TTL, LIMIT)
    interest = await active(session, user.id, film.id)
    await set_age(session, interest.id, TTL + 3)

    state = await marks.set_mark(session, user.id, film.id, InterestKind.SOON, TTL, LIMIT)
    assert state.effective_kind == InterestKind.SOON
    assert state.can_renew_soon is False

    fresh = await active(session, user.id, film.id)
    assert fresh.id != interest.id  # поставлена заново, срок пошёл сначала


async def test_expired_soon_does_not_eat_the_limit(session):
    """Просроченные «Ближайшие» ведут себя как «Желаемое» и место не занимают."""
    user = await make_user(session, "Активный")
    films = [await make_film(session, f"Фильм {i}") for i in range(LIMIT + 1)]
    await session.commit()

    for film in films[:LIMIT]:
        await marks.set_mark(session, user.id, film.id, InterestKind.SOON, TTL, LIMIT)

    with pytest.raises(InterestError, match="Лимит"):
        await marks.set_mark(session, user.id, films[LIMIT].id, InterestKind.SOON, TTL, LIMIT)

    # Состарим одну — место должно освободиться.
    stale = await active(session, user.id, films[0].id)
    await set_age(session, stale.id, TTL + 1)

    state = await marks.set_mark(session, user.id, films[LIMIT].id, InterestKind.SOON, TTL, LIMIT)
    assert state.effective_kind == InterestKind.SOON


async def test_watched_does_not_block_wishlist(session):
    """«Просмотрено» не отменяет желания сходить снова."""
    user, film = await pair(session)

    state = await marks.set_watched(session, user.id, film.id, True, TTL)
    assert state.watched is True
    assert state.effective_kind is None

    state = await marks.set_mark(session, user.id, film.id, InterestKind.WISHLIST, TTL, LIMIT)
    assert state.watched is True
    assert state.effective_kind == InterestKind.WISHLIST


async def test_watched_toggles_off(session):
    user, film = await pair(session)
    await marks.set_watched(session, user.id, film.id, True, TTL)
    state = await marks.set_watched(session, user.id, film.id, False, TTL)

    assert state.watched is False
    assert await session.scalar(sa.select(sa.func.count()).select_from(Watch)) == 0


async def test_watched_is_idempotent(session):
    user, film = await pair(session)
    await marks.set_watched(session, user.id, film.id, True, TTL)
    await marks.set_watched(session, user.id, film.id, True, TTL)
    assert await session.scalar(sa.select(sa.func.count()).select_from(Watch)) == 1


async def test_batch_states_match_single_lookup(session):
    """Списочный путь не должен расходиться с одиночным."""
    user = await make_user(session, "Зритель")
    wished = await make_film(session, "Желаемое")
    soon = await make_film(session, "Ближайшее")
    expired = await make_film(session, "Просроченное")
    untouched = await make_film(session, "Нетронутое")
    await session.commit()

    await marks.set_mark(session, user.id, wished.id, InterestKind.WISHLIST, TTL, LIMIT)
    await marks.set_mark(session, user.id, soon.id, InterestKind.SOON, TTL, LIMIT)
    await marks.set_mark(session, user.id, expired.id, InterestKind.SOON, TTL, LIMIT)
    await set_age(session, (await active(session, user.id, expired.id)).id, TTL + 1)
    await marks.set_watched(session, user.id, untouched.id, True, TTL)

    ids = [wished.id, soon.id, expired.id, untouched.id]
    batch = await marks.marks_for_films(session, user.id, ids, TTL)

    for film_id in ids:
        single = await marks.state(session, user.id, film_id, TTL)
        assert batch[film_id].effective_kind == single.effective_kind
        assert batch[film_id].can_renew_soon == single.can_renew_soon
        assert batch[film_id].watched == single.watched

    assert batch[expired.id].effective_kind == InterestKind.WISHLIST
    assert batch[untouched.id].effective_kind is None
    assert batch[untouched.id].watched is True
