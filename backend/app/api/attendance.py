"""Этап 4 — присутствие и обратная связь (§8)."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireModerator
from app.db import get_session
from app.models import Attendance, Feedback, Film, Screening, User
from app.schemas import (
    AttendeeOut,
    CodeOut,
    FeedbackIn,
    FeedbackOut,
    MarkCodeIn,
    OrgRating,
)
from app.services import attendance as att
from app.services.attendance import AttendanceError
from app.services.settings import SettingsService
from app.services.tmdb import poster_url

router = APIRouter(prefix="/api/screenings", tags=["attendance"])


async def _screening_or_404(session: AsyncSession, screening_id: int) -> Screening:
    screening = await session.get(Screening, screening_id)
    if screening is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Показ не найден")
    return screening


@router.get("/{screening_id}/code", response_model=CodeOut)
async def code(
    screening_id: int,
    moderator: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CodeOut:
    """Код для экрана в зале. Обновляется сам — фронт перезапрашивает по таймеру."""
    from datetime import UTC, datetime

    screening = await _screening_or_404(session, screening_id)
    values = await SettingsService(session).all()
    rotation = int(values["code_rotation_seconds"])
    window = int(values["attendance_window_minutes"])

    info = await att.current_code(session, screening, rotation)
    marked = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Attendance)
        .where(Attendance.screening_id == screening_id)
    )
    return CodeOut(
        screening_id=screening_id,
        code=info.code,
        valid_for=info.valid_for,
        rotates_every=info.rotates_every,
        window_open=await att.window_is_open(session, screening, window, datetime.now(UTC)),
        attendees=marked or 0,
    )


@router.post("/{screening_id}/attend", response_model=FeedbackOut)
async def attend(
    screening_id: int,
    body: MarkCodeIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackOut:
    values = await SettingsService(session).all()
    try:
        await att.mark_by_code(
            session,
            screening_id,
            user.id,
            body.code,
            rotation_seconds=int(values["code_rotation_seconds"]),
            window_minutes=int(values["attendance_window_minutes"]),
        )
    except AttendanceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _feedback_out(session, screening_id, user.id)


@router.post("/{screening_id}/attendees/{user_id}", response_model=list[AttendeeOut])
async def add_by_hand(
    screening_id: int,
    user_id: int,
    moderator: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AttendeeOut]:
    """Модератор может добавить человека вручную (§8)."""
    try:
        await att.mark_manually(session, screening_id, user_id, moderator.id)
    except AttendanceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _attendees(session, screening_id)


@router.get("/{screening_id}/attendees", response_model=list[AttendeeOut])
async def attendees(
    screening_id: int,
    moderator: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AttendeeOut]:
    """Живой список отметившихся — его видит модератор в зале."""
    return await _attendees(session, screening_id)


async def _attendees(session: AsyncSession, screening_id: int) -> list[AttendeeOut]:
    rows = await session.execute(
        sa.select(Attendance, User.display_name)
        .join(User, User.id == Attendance.user_id)
        .where(Attendance.screening_id == screening_id)
        .order_by(Attendance.marked_at)
    )
    return [
        AttendeeOut(
            user_id=item.user_id,
            display_name=name,
            method=item.method,
            marked_at=item.marked_at,
        )
        for item, name in rows
    ]


@router.get("/{screening_id}/feedback", response_model=FeedbackOut)
async def get_feedback(
    screening_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackOut:
    return await _feedback_out(session, screening_id, user.id)


@router.put("/{screening_id}/feedback", response_model=FeedbackOut)
async def put_feedback(
    screening_id: int,
    body: FeedbackIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackOut:
    try:
        await att.save_feedback(
            session,
            screening_id,
            user.id,
            body.film_rating,
            body.review_text,
            body.org.model_dump() if body.org else None,
        )
    except AttendanceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _feedback_out(session, screening_id, user.id)


async def _feedback_out(
    session: AsyncSession, screening_id: int, user_id: int
) -> FeedbackOut:
    screening = await _screening_or_404(session, screening_id)
    film = await session.get(Film, screening.film_id)

    came = await session.scalar(
        sa.select(Attendance.id).where(
            Attendance.screening_id == screening_id, Attendance.user_id == user_id
        )
    )
    saved = (
        await session.execute(
            sa.select(Feedback).where(
                Feedback.screening_id == screening_id, Feedback.user_id == user_id
            )
        )
    ).scalar_one_or_none()

    from app.schemas import FilmBrief

    return FeedbackOut(
        screening_id=screening_id,
        film=FilmBrief(
            id=film.id,
            tmdb_id=film.tmdb_id,
            title_ru=film.title_ru,
            title_orig=film.title_orig,
            year=film.year,
            poster_url=poster_url(film.poster_path),
            genres=list(film.genres or []),
            directors=list(film.directors or []),
        ),
        attended=came is not None,
        film_rating=saved.film_rating if saved else None,
        review_text=saved.review_text if saved else None,
        org=(
            OrgRating(
                sound=saved.org_sound,
                picture=saved.org_picture,
                hall=saved.org_hall,
                time=saved.org_time,
                comment=saved.org_comment,
            )
            if saved
            else None
        ),
    )
