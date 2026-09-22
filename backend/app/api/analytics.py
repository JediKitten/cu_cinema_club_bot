"""Аналитика и календарь прошедших показов (§14, §18 п.10)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireAdmin
from app.db import get_session
from app.models import AuditLog
from app.schemas import (
    AnalyticsOut,
    CsatWeek,
    ExportPasswordIn,
    ExportPasswordOut,
    FunnelStep,
    OverviewOut,
    PastScreeningOut,
)
from app.services import analytics, analytics_gate
from app.services.settings import SettingsService
from app.services.tmdb import poster_url
from app.services.weights import WeightParams

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/admin/analytics", response_model=AnalyticsOut)
async def full_analytics(
    admin: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> AnalyticsOut:
    """Полная аналитика — главному админу и админам (§9)."""
    values = await SettingsService(session).all()

    steps = await analytics.funnel(session)
    overview = await analytics.overview(
        session, int(values["long_wait_days"]), WeightParams.from_settings(values)
    )

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
            cancelled_share=overview.cancelled_share,
            by_weekday=overview.by_weekday,
            long_wait_films=overview.long_wait_films,
            audience_by_week=overview.audience_by_week,
            no_show_users=overview.no_show_users,
            soon_churn=overview.soon_churn,
            csat_by_week=[
                CsatWeek.model_validate(week, from_attributes=True)
                for week in overview.csat_by_week
            ],
        ),
        top_rated=await analytics.top_rated(
            session, int(values["internal_rating_min_votes"])
        ),
    )


def _password_out(state: analytics_gate.State) -> ExportPasswordOut:
    return ExportPasswordOut(
        is_set=state.is_set, updated_at=state.updated_at, updated_by=state.updated_by
    )


@router.get("/admin/analytics/password", response_model=ExportPasswordOut)
async def export_password(
    admin: RequireAdmin, session: Annotated[AsyncSession, Depends(get_session)]
) -> ExportPasswordOut:
    """Задан ли пароль на /analytics. Самого пароля не отдаём никому и никогда:
    в базе лежит хеш, и восстановить из него строку нельзя — можно только
    поставить новую."""
    return _password_out(await analytics_gate.state(session))


@router.put("/admin/analytics/password", response_model=ExportPasswordOut)
async def set_export_password(
    body: ExportPasswordIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExportPasswordOut:
    """Ставит или снимает пароль на выгрузку в боте. Пустая строка выключает
    команду вовсе — это и есть способ закрыть доступ, когда пароль разошёлся."""
    try:
        await analytics_gate.set_password(session, body.password, admin.id)
    except analytics_gate.GateError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    session.add(
        AuditLog(
            actor_id=admin.id,
            entity="analytics_export",
            action="password_set" if body.password.strip() else "password_cleared",
        )
    )
    await session.commit()
    return _password_out(await analytics_gate.state(session))


@router.get("/screenings/past", response_model=list[PastScreeningOut])
async def past(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[PastScreeningOut]:
    """Календарь прошедших показов — виден всем участникам клуба."""
    rows = await analytics.past_screenings(session, viewer_id=user.id)
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
            i_attended=row["i_attended"],
            i_answered=row["i_answered"],
        )
        for row in rows
    ]
