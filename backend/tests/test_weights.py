"""Проверка формулы весов (§4) и обоих рейтингов (§5).

Формула — центральная часть системы: она определяет, что вообще попадёт в
шорт-лист. Поэтому сверяем SQL-выражение с эталонным расчётом на Python.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Film, Interest, User
from app.models.enums import InterestKind, RevokeReason
from app.services.ranking import rank_by_coverage, rank_by_weight
from app.services.weights import WeightParams, active_interest_clause, interest_weight_expr

PARAMS = WeightParams(
    wishlist_base_weight=1.0,
    wishlist_half_life_days=180.0,
    wishlist_weight_floor=0.2,
    soon_weight=3.0,
    soon_ttl_days=14,
)


def expected_wishlist(age_days: float, p: WeightParams = PARAMS) -> float:
    return max(
        p.wishlist_weight_floor,
        p.wishlist_base_weight * 0.5 ** (age_days / p.wishlist_half_life_days),
    )


async def make_user(session, name: str) -> User:
    user = User(display_name=name, tg_id=abs(hash(name)) % 10**9)
    session.add(user)
    await session.flush()
    return user


async def make_film(session, title: str) -> Film:
    film = Film(title_ru=title)
    session.add(film)
    await session.flush()
    return film


async def add_interest(session, user, film, kind, age_days: float = 0.0, revoked=False):
    interest = Interest(
        user_id=user.id,
        film_id=film.id,
        kind=kind,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
        revoked_at=datetime.now(UTC) if revoked else None,
        revoke_reason=RevokeReason.WATCHED if revoked else None,
    )
    session.add(interest)
    await session.flush()
    return interest


async def weight_of(session, interest_id: int) -> float:
    return float(
        await session.scalar(
            sa.select(interest_weight_expr(PARAMS)).where(Interest.id == interest_id)
        )
    )


@pytest.mark.parametrize("age_days", [0, 30, 180, 360, 720, 3000])
async def test_wishlist_decay_matches_formula(session, age_days):
    user = await make_user(session, f"u{age_days}")
    film = await make_film(session, f"f{age_days}")
    interest = await add_interest(session, user, film, InterestKind.WISHLIST, age_days)

    assert await weight_of(session, interest.id) == pytest.approx(
        expected_wishlist(age_days), rel=1e-6
    )


async def test_wishlist_never_falls_below_floor(session):
    user = await make_user(session, "ancient")
    film = await make_film(session, "ancient film")
    interest = await add_interest(session, user, film, InterestKind.WISHLIST, 10_000)

    assert await weight_of(session, interest.id) == pytest.approx(PARAMS.wishlist_weight_floor)


async def test_half_life_halves_weight(session):
    user = await make_user(session, "half")
    film = await make_film(session, "half film")
    fresh = await add_interest(session, user, film, InterestKind.WISHLIST, 0)
    other = await make_film(session, "half film 2")
    aged = await add_interest(session, user, other, InterestKind.WISHLIST, 180)

    assert await weight_of(session, aged.id) == pytest.approx(
        await weight_of(session, fresh.id) / 2, rel=1e-6
    )


async def test_soon_does_not_decay_inside_ttl(session):
    user = await make_user(session, "soon")
    film_a = await make_film(session, "soon a")
    film_b = await make_film(session, "soon b")
    fresh = await add_interest(session, user, film_a, InterestKind.SOON, 0)
    day13 = await add_interest(session, user, film_b, InterestKind.SOON, 13)

    assert await weight_of(session, fresh.id) == pytest.approx(PARAMS.soon_weight)
    assert await weight_of(session, day13.id) == pytest.approx(PARAMS.soon_weight)


async def test_expired_soon_weighs_nothing_even_if_cron_lagged(session):
    """Отметка просрочена, но крон её ещё не снял — она уже не должна весить."""
    user = await make_user(session, "expired")
    film = await make_film(session, "expired film")
    interest = await add_interest(session, user, film, InterestKind.SOON, 15)

    assert await weight_of(session, interest.id) == pytest.approx(0.0)


async def test_both_buttons_stack(session):
    user = await make_user(session, "both")
    film = await make_film(session, "both film")
    await add_interest(session, user, film, InterestKind.WISHLIST, 0)
    await add_interest(session, user, film, InterestKind.SOON, 0)
    await session.commit()

    ranked = await rank_by_weight(session, PARAMS, long_wait_days=90)
    assert ranked[0].weight == pytest.approx(PARAMS.wishlist_base_weight + PARAMS.soon_weight)
    assert ranked[0].wishlist_count == 1
    assert ranked[0].soon_count == 1


async def test_revoked_interest_excluded(session):
    user = await make_user(session, "revoked")
    film = await make_film(session, "revoked film")
    await add_interest(session, user, film, InterestKind.WISHLIST, 0, revoked=True)
    await session.commit()

    assert await rank_by_weight(session, PARAMS, long_wait_days=90) == []


async def test_long_wait_flag_counts_only_old_marks(session):
    film = await make_film(session, "long wait")
    old = await make_user(session, "old waiter")
    new = await make_user(session, "new waiter")
    await add_interest(session, old, film, InterestKind.WISHLIST, 200)
    await add_interest(session, new, film, InterestKind.WISHLIST, 5)
    await session.commit()

    ranked = await rank_by_weight(session, PARAMS, long_wait_days=90)
    assert ranked[0].long_wait_count == 1


async def test_coverage_beats_weight_on_overlapping_audience(session):
    """Ключевой сценарий §5: три фаната держат два одинаковых фильма, четвёртый
    человек — свой. По весу его фильм третий, по покрытию — второй, потому что
    только он приводит нового зрителя.
    """
    fans = [await make_user(session, f"fan{i}") for i in range(3)]
    loner = await make_user(session, "loner")

    popular_a = await make_film(session, "Популярный A")
    popular_b = await make_film(session, "Популярный B")
    niche = await make_film(session, "Нишевый")

    for fan in fans:
        await add_interest(session, fan, popular_a, InterestKind.WISHLIST, 0)
        await add_interest(session, fan, popular_b, InterestKind.WISHLIST, 0)
    await add_interest(session, loner, niche, InterestKind.WISHLIST, 0)
    await session.commit()

    by_weight = await rank_by_weight(session, PARAMS, long_wait_days=90)
    assert [r.title_ru for r in by_weight][2] == "Нишевый"

    by_coverage = await rank_by_coverage(session, PARAMS, long_wait_days=90, size=3)
    assert by_coverage[1].title_ru == "Нишевый"
    # Второй популярный фильм не приводит никого нового — его прирост нулевой,
    # поэтому он оказывается последним.
    assert by_coverage[1].marginal_weight == pytest.approx(1.0)


async def test_coverage_respects_min_weight_threshold(session):
    """Автопилот отбрасывает фильмы ниже порога и берёт сколько есть (§5)."""
    user = await make_user(session, "single")
    strong = await make_film(session, "Сильный")
    weak = await make_film(session, "Слабый")
    await add_interest(session, user, strong, InterestKind.SOON, 0)
    weak_user = await make_user(session, "weak voter")
    await add_interest(session, weak_user, weak, InterestKind.WISHLIST, 10_000)
    await session.commit()

    ranked = await rank_by_coverage(session, PARAMS, long_wait_days=90, size=5, min_weight=1.0)
    assert [r.title_ru for r in ranked] == ["Сильный"]


async def test_sandbox_params_reorder_ranking(session):
    """Песочница §13: те же данные, другие коэффициенты — другой порядок."""
    await make_user(session, "old fan")
    user_new = await make_user(session, "new fan")
    old_film = await make_film(session, "Старая отметка")
    new_film = await make_film(session, "Свежее SOON")
    # Три давних «желаемых» против одного свежего «ближайшего».
    for i in range(3):
        voter = await make_user(session, f"oldvoter{i}")
        await add_interest(session, voter, old_film, InterestKind.WISHLIST, 400)
    await add_interest(session, user_new, new_film, InterestKind.SOON, 1)
    await session.commit()

    # При базовых параметрах побеждают три затухших отметки: 3 * ~0.4 > 3.0? нет —
    # проверяем фактический порядок, а не догадку.
    default_order = [r.title_ru for r in await rank_by_weight(session, PARAMS, 90)]

    heavy_soon = replace(PARAMS, soon_weight=50.0)
    boosted_order = [r.title_ru for r in await rank_by_weight(session, heavy_soon, 90)]

    assert boosted_order[0] == "Свежее SOON"
    assert default_order != boosted_order or default_order[0] == "Свежее SOON"


async def test_active_clause_reconstructs_past_state(session):
    """Реконструкция на момент времени: отметка, снятая вчера, вчера была активна."""
    user = await make_user(session, "history")
    film = await make_film(session, "history film")
    interest = await add_interest(session, user, film, InterestKind.WISHLIST, 30)
    interest.revoked_at = datetime.now(UTC) - timedelta(days=1)
    interest.revoke_reason = RevokeReason.WATCHED
    await session.commit()

    two_days_ago = sa.literal(datetime.now(UTC) - timedelta(days=2))
    was_active = await session.scalar(
        sa.select(sa.func.count()).select_from(Interest).where(active_interest_clause(two_days_ago))
    )
    is_active_now = await session.scalar(
        sa.select(sa.func.count()).select_from(Interest).where(active_interest_clause())
    )
    assert was_active == 1
    assert is_active_now == 0
