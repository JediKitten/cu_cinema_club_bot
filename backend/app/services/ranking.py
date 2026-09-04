"""Два рейтинга этапа 1 → 2 (§5 спека).

Оба строятся по одним и тем же данным: рейтинг по весу — простая сортировка,
рейтинг по покрытию аудитории — жадный алгоритм, на каждом шаге считающий вес
только по «непокрытым» пользователям.
"""

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Feedback, Film, Interest, Screening
from app.models.enums import FilmStatus, InterestKind, ScreeningStatus
from app.services.weights import WeightParams, active_interest_clause, interest_weight_expr


@dataclass(slots=True)
class FilmRank:
    film_id: int
    title_ru: str
    title_orig: str | None
    year: int | None
    poster_path: str | None
    weight: float
    wishlist_count: int
    soon_count: int
    long_wait_count: int
    ext_rating: float | None
    ext_votes: int | None
    internal_rating: float | None = None
    internal_votes: int = 0
    screening_history: list[dict] = field(default_factory=list)
    # Заполняется только в рейтинге по покрытию: прирост охвата на своём шаге.
    marginal_weight: float | None = None


async def _pair_weights(session: AsyncSession, params: WeightParams) -> dict[int, dict[int, float]]:
    """{film_id: {user_id: суммарный вес отметок этого пользователя на фильм}}.

    Именно пары нужны обоим рейтингам: по весу — как сумма, по покрытию — чтобы
    вычитать уже покрытых пользователей.
    """
    weight = interest_weight_expr(params)
    stmt = (
        sa.select(
            Interest.film_id,
            Interest.user_id,
            sa.func.sum(weight).label("w"),
        )
        .join(Film, Film.id == Interest.film_id)
        .where(active_interest_clause(), Film.status == FilmStatus.ACTIVE)
        .group_by(Interest.film_id, Interest.user_id)
    )
    pairs: dict[int, dict[int, float]] = {}
    for film_id, user_id, w in await session.execute(stmt):
        pairs.setdefault(film_id, {})[user_id] = float(w)
    return pairs


async def _film_facts(
    session: AsyncSession, params: WeightParams, long_wait_days: int, film_ids: list[int]
) -> dict[int, FilmRank]:
    """Карточка фильма для админского списка: счётчики отметок, флаг «давно ждут»,
    внутренний рейтинг, история показов."""
    if not film_ids:
        return {}

    age_days = sa.extract("epoch", sa.func.now() - Interest.created_at) / 86400.0
    counts = (
        sa.select(
            Interest.film_id,
            sa.func.count().filter(Interest.kind == InterestKind.WISHLIST).label("wishlist_count"),
            sa.func.count().filter(Interest.kind == InterestKind.SOON).label("soon_count"),
            sa.func.count(sa.distinct(Interest.user_id))
            .filter(age_days > long_wait_days)
            .label("long_wait_count"),
            sa.func.sum(interest_weight_expr(params)).label("weight"),
        )
        .where(active_interest_clause(), Interest.film_id.in_(film_ids))
        .group_by(Interest.film_id)
    )

    rows: dict[int, FilmRank] = {}
    films = {
        f.id: f
        for f in (await session.execute(sa.select(Film).where(Film.id.in_(film_ids)))).scalars()
    }
    for film_id, wishlist_count, soon_count, long_wait_count, weight in await session.execute(
        counts
    ):
        film = films[film_id]
        rows[film_id] = FilmRank(
            film_id=film_id,
            title_ru=film.title_ru,
            title_orig=film.title_orig,
            year=film.year,
            poster_path=film.poster_path,
            weight=float(weight or 0.0),
            wishlist_count=wishlist_count,
            soon_count=soon_count,
            long_wait_count=long_wait_count,
            ext_rating=film.ext_rating,
            ext_votes=film.ext_votes,
        )

    internal = await session.execute(
        sa.select(
            Feedback.film_id,
            sa.func.avg(Feedback.film_rating),
            sa.func.count(Feedback.film_rating),
        )
        .where(Feedback.film_id.in_(film_ids), Feedback.film_rating.is_not(None))
        .group_by(Feedback.film_id)
    )
    for film_id, avg, count in internal:
        if row := rows.get(film_id):
            row.internal_rating = round(float(avg), 2)
            row.internal_votes = count

    # История показов: админу при отборе показывается, когда фильм уже крутили,
    # с ожидаемой и фактической явкой (§5, §8 — кулдаунов нет, но контекст нужен).
    history = await session.execute(
        sa.select(Screening)
        .where(Screening.film_id.in_(film_ids), Screening.status != ScreeningStatus.CANCELLED)
        .order_by(Screening.created_at.desc())
    )
    for screening in history.scalars():
        if row := rows.get(screening.film_id):
            row.screening_history.append(
                {
                    "screening_id": screening.id,
                    "status": screening.status,
                    "expected_attendance": screening.expected_attendance,
                }
            )
    return rows


async def rank_by_weight(
    session: AsyncSession, params: WeightParams, long_wait_days: int, limit: int = 50
) -> list[FilmRank]:
    pairs = await _pair_weights(session, params)
    totals = {fid: sum(users.values()) for fid, users in pairs.items()}
    top = sorted(totals, key=lambda fid: -totals[fid])[:limit]
    facts = await _film_facts(session, params, long_wait_days, top)
    return [facts[fid] for fid in top if fid in facts]


async def rank_by_coverage(
    session: AsyncSession,
    params: WeightParams,
    long_wait_days: int,
    size: int,
    min_weight: float = 0.0,
) -> list[FilmRank]:
    """Жадное покрытие: шаг 1 — фильм с максимальным весом; шаг N — фильм с
    максимальным весом, считая только тех пользователей, чьи отметки ещё не
    покрыты ни одним выбранным фильмом."""
    pairs = await _pair_weights(session, params)
    covered: set[int] = set()
    chosen: list[tuple[int, float]] = []

    for _ in range(size):
        best_film, best_gain = None, 0.0
        for film_id, users in pairs.items():
            if any(film_id == c for c, _ in chosen):
                continue
            gain = sum(w for uid, w in users.items() if uid not in covered)
            if gain > best_gain:
                best_film, best_gain = film_id, gain
        # Порог применяется к приросту: фильм, который никого нового не приводит,
        # в шорт-листе бесполезен, каким бы ни был его абсолютный вес.
        if best_film is None or best_gain < min_weight:
            break
        chosen.append((best_film, best_gain))
        covered |= set(pairs[best_film])

    facts = await _film_facts(session, params, long_wait_days, [fid for fid, _ in chosen])
    result = []
    for film_id, gain in chosen:
        if row := facts.get(film_id):
            row.marginal_weight = round(gain, 3)
            result.append(row)
    return result
