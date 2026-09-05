"""Аналитика и календарь прошедших показов (§14, §18 п.10)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireAdmin
from app.db import get_session
from app.schemas import AnalyticsOut, FunnelStep, OverviewOut, PastScreeningOut
from app.services import analytics
from app.services.settings import SettingsService
from app.services.tmdb import poster_url

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/admin/analytics", response_model=AnalyticsOut)
async def full_analytics(
    admin: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> AnalyticsOut:
    """Полная аналитика — главному админу и админам (§9)."""
    values = await SettingsService(session).all()

    steps = await analytics.funnel(session)
    overview = await analytics.overview(session, int(values["long_wait_days"]))

    return AnalyticsOut(
        funnel=[FunnelStep(**step.as_dict()) for step in steps],
        overview=OverviewOut(
            rounds=overview.rounds,
            screenings_held=overview.screenings_held,
            screenings_cancelled=overview.screenings_cancelled,
            average_attendance=overview.average_attendance,
            hall_fill_rate=overview.hall_fill_rate,
            active_users=overview.active_users,
            no_show_rate=overview.no_show_rate,
            late_cancels=overview.late_cancels,
            by_weekday=overview.by_weekday,
            long_wait_films=overview.long_wait_films,
        ),
        top_rated=await analytics.top_rated(
            session, int(values["internal_rating_min_votes"])
        ),
    )


@router.get("/screenings/past", response_model=list[PastScreeningOut])
async def past(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[PastScreeningOut]:
    """Календарь прошедших показов — виден всем участникам клуба."""
    rows = await analytics.past_screenings(session)
    return [
        PastScreeningOut(
            screening_id=row["screening_id"],
            film_id=row["film_id"],
            title=row["title"],
            year=row["year"],
            poster_url=poster_url(row["poster_path"]),
            starts_at=row["starts_at"],
            status=row["status"],
            expected=row["expected"],
            came=row["came"],
            rating=row["rating"],
        )
        for row in rows
    ]
