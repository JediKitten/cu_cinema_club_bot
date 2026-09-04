from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import RequireAdmin, RequireSuperadmin
from app.db import get_session
from app.models import AuditLog
from app.schemas import RankingsOut, RankRow, SandboxIn, SettingOut, SettingsPatch
from app.services.ranking import FilmRank, rank_by_coverage, rank_by_weight
from app.services.settings import REGISTRY, SettingsError, SettingsService
from app.services.tmdb import poster_url
from app.services.weights import WeightParams

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _row(rank: FilmRank) -> RankRow:
    return RankRow(
        film_id=rank.film_id,
        title_ru=rank.title_ru,
        title_orig=rank.title_orig,
        year=rank.year,
        poster_url=poster_url(rank.poster_path),
        weight=round(rank.weight, 3),
        wishlist_count=rank.wishlist_count,
        soon_count=rank.soon_count,
        long_wait_count=rank.long_wait_count,
        ext_rating=rank.ext_rating,
        ext_votes=rank.ext_votes,
        internal_rating=rank.internal_rating,
        internal_votes=rank.internal_votes,
        marginal_weight=rank.marginal_weight,
        screening_history=rank.screening_history,
    )


@router.get("/settings", response_model=list[SettingOut])
async def list_settings(
    admin: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[SettingOut]:
    values = await SettingsService(session).all()
    return [
        SettingOut(
            key=spec.key,
            value=values[spec.key],
            type=spec.type,
            group=spec.group,
            label=spec.label,
            help=spec.help,
            min=spec.min,
            max=spec.max,
            affects_weights=spec.affects_weights,
        )
        for spec in REGISTRY
    ]


@router.patch("/settings", response_model=list[SettingOut])
async def update_settings(
    body: SettingsPatch,
    admin: RequireSuperadmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SettingOut]:
    """Правка параметров — только главный админ (§9)."""
    service = SettingsService(session)
    try:
        applied = await service.set_many(body.values, admin.id)
    except SettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    session.add(AuditLog(actor_id=admin.id, entity="settings", action="update", payload=applied))
    await session.commit()
    return await list_settings(admin, session)


@router.get("/rankings", response_model=RankingsOut)
async def rankings(
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RankingsOut:
    """Два независимых рейтинга по одним и тем же данным (§5)."""
    values = await SettingsService(session).all()
    params = WeightParams.from_settings(values)
    long_wait = int(values["long_wait_days"])

    by_weight = await rank_by_weight(session, params, long_wait, limit)
    by_coverage = await rank_by_coverage(session, params, long_wait, int(values["shortlist_size"]))
    return RankingsOut(
        by_weight=[_row(r) for r in by_weight],
        by_coverage=[_row(r) for r in by_coverage],
    )


@router.post("/settings/sandbox", response_model=RankingsOut)
async def sandbox(
    body: SandboxIn,
    admin: RequireSuperadmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RankingsOut:
    """Песочница весов (§13): рейтинг с указанными коэффициентами, без сохранения.

    Работает бесплатно ровно потому, что вес нигде не материализован — достаточно
    подставить другие коэффициенты в то же выражение.
    """
    values = await SettingsService(session).all()
    params = WeightParams.from_settings(
        values,
        wishlist_base_weight=body.wishlist_base_weight,
        wishlist_half_life_days=body.wishlist_half_life_days,
        wishlist_weight_floor=body.wishlist_weight_floor,
        soon_weight=body.soon_weight,
        soon_ttl_days=body.soon_ttl_days,
    )
    long_wait = int(values["long_wait_days"])
    by_weight = await rank_by_weight(session, params, long_wait, body.limit)
    by_coverage = await rank_by_coverage(session, params, long_wait, int(values["shortlist_size"]))
    return RankingsOut(
        by_weight=[_row(r) for r in by_weight],
        by_coverage=[_row(r) for r in by_coverage],
    )
