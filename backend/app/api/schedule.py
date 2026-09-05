"""Этап 3 — расписание и подтверждения (§7)."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireAdmin, RequireModerator
from app.db import get_session
from app.models import Confirmation, Film, FilmVote, Hall, Round, Screening, Slot
from app.models.enums import ConfirmationState, RoundStage
from app.schemas import (
    AssignIn,
    CancelIn,
    ConfirmOut,
    FilmBrief,
    MoveIn,
    ScheduleOut,
    ScreeningOut,
    SlotOut,
)
from app.services import events as events_service
from app.services import rounds as rounds_service
from app.services import schedule as schedule_service
from app.services.schedule import ScheduleError
from app.services.settings import SettingsService
from app.services.tmdb import poster_url

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


def _placeholder(screening: Screening) -> FilmBrief:
    """Событие без фильма: название ещё не объявлено («ждите анонса»)."""
    return FilmBrief(
        id=None,
        tmdb_id=None,
        title_ru=screening.title or "Событие клуба",
        title_orig=None,
        year=None,
        poster_url=None,
        in_catalog=False,
    )


def _film_brief(film: Film) -> FilmBrief:
    return FilmBrief(
        id=film.id,
        tmdb_id=film.tmdb_id,
        title_ru=film.title_ru,
        title_orig=film.title_orig,
        year=film.year,
        poster_url=poster_url(film.poster_path),
        genres=list(film.genres or []),
        directors=list(film.directors or []),
    )


async def _manual_rows(session: AsyncSession):
    """События, назначенные вручную. Они вне цикла, поэтому подтягиваются отдельно."""
    events = await events_service.upcoming(session)
    out = []
    for event in events:
        slot = await session.get(Slot, event.slot_id)
        film = await session.get(Film, event.film_id) if event.film_id else None
        out.append((event, film, slot))
    return out


async def _round_or_404(session: AsyncSession) -> Round:
    round_ = await rounds_service.active_round(session)
    if round_ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активного цикла нет")
    return round_


async def _build(session: AsyncSession, round_: Round, user_id: int) -> ScheduleOut:
    rows = await schedule_service.screenings_of(session, round_)
    rows += await _manual_rows(session)
    rows.sort(key=lambda item: item[2].starts_at)
    halls = {hall.id: hall for hall in (await session.execute(sa.select(Hall))).scalars()}

    ids = [screening.id for screening, _, _ in rows]
    mine = {
        confirmation.screening_id: confirmation
        for confirmation in (
            await session.execute(
                sa.select(Confirmation).where(
                    Confirmation.screening_id.in_(ids), Confirmation.user_id == user_id
                )
            )
        ).scalars()
    }
    voted_films = set(
        (
            await session.execute(
                sa.select(FilmVote.film_id).where(
                    FilmVote.round_id == round_.id, FilmVote.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    counts = dict(
        (
            await session.execute(
                sa.select(Confirmation.screening_id, sa.func.count())
                .where(
                    Confirmation.screening_id.in_(ids),
                    Confirmation.state == ConfirmationState.CONFIRMED,
                )
                .group_by(Confirmation.screening_id)
            )
        ).all()
    )

    out = []
    for screening, film, slot in rows:
        hall = halls[slot.hall_id]
        confirmation = mine.get(screening.id)
        place = None
        if confirmation is not None and confirmation.state == ConfirmationState.WAITLIST:
            place = (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(Confirmation)
                    .where(
                        Confirmation.screening_id == screening.id,
                        Confirmation.state == ConfirmationState.WAITLIST,
                        Confirmation.created_at < confirmation.created_at,
                    )
                )
                or 0
            ) + 1

        out.append(
            ScreeningOut(
                id=screening.id,
                film=_film_brief(film) if film else _placeholder(screening),
                slot=SlotOut(
                    id=slot.id,
                    starts_at=slot.starts_at,
                    duration_min=slot.duration_min,
                    blocked=slot.blocked,
                    blocked_reason=slot.blocked_reason,
                    hall_name=hall.name,
                    hall_capacity=hall.capacity,
                ),
                status=screening.status,
                expected_attendance=screening.expected_attendance,
                cancel_reason=screening.cancel_reason,
                is_manual=screening.is_manual,
                note=screening.note,
                my_state=confirmation.state if confirmation else None,
                my_place_in_queue=place,
                confirmed=counts.get(screening.id, 0),
                capacity=hall.capacity,
                invited=film.id in voted_films,
            )
        )

    return ScheduleOut(
        round_id=round_.id,
        week_start=round_.week_start,
        stage=round_.stage,
        published=round_.stage in (RoundStage.PUBLISHED, RoundStage.RUNNING, RoundStage.CLOSED),
        screenings=out,
    )


@router.get("", response_model=ScheduleOut)
async def schedule(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> ScheduleOut:
    """Расписание недели. До публикации видно только тем, кто его составляет."""
    round_ = await _round_or_404(session)
    if round_.stage in (RoundStage.COLLECTING, RoundStage.SHORTLIST_REVIEW, RoundStage.SLOT_VOTING):
        if user.role.rank < 1:  # ниже модератора
            raise HTTPException(status.HTTP_409_CONFLICT, "Расписание ещё не опубликовано")
    return await _build(session, round_, user.id)


# --- Расстановка (модератор и выше) ----------------------------------------


@router.post("/assign", response_model=ScheduleOut)
async def assign(
    body: AssignIn,
    admin: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScheduleOut:
    round_ = await _round_or_404(session)
    try:
        await schedule_service.assign(session, round_, body.film_id, body.slot_id, admin.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _build(session, round_, admin.id)


@router.delete("/screenings/{screening_id}", response_model=ScheduleOut)
async def unassign(
    screening_id: int,
    admin: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScheduleOut:
    round_ = await _round_or_404(session)
    try:
        await schedule_service.unassign(session, round_, screening_id, admin.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _build(session, round_, admin.id)


@router.post("/publish", response_model=ScheduleOut)
async def publish(
    admin: RequireModerator, session: Annotated[AsyncSession, Depends(get_session)]
) -> ScheduleOut:
    round_ = await _round_or_404(session)
    try:
        await schedule_service.publish_schedule(session, round_, admin.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _build(session, round_, admin.id)


@router.post("/screenings/{screening_id}/move", response_model=ScheduleOut)
async def move(
    screening_id: int,
    body: MoveIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScheduleOut:
    """Правка опубликованного расписания — только админ (§9)."""
    round_ = await _round_or_404(session)
    try:
        await schedule_service.move_screening(session, screening_id, body.slot_id, admin.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _build(session, round_, admin.id)


@router.post("/screenings/{screening_id}/cancel", response_model=ScheduleOut)
async def cancel_screening(
    screening_id: int,
    body: CancelIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScheduleOut:
    round_ = await _round_or_404(session)
    try:
        await schedule_service.cancel_screening(session, screening_id, body.reason, admin.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _build(session, round_, admin.id)


# --- Подтверждения (все) ---------------------------------------------------


@router.post("/screenings/{screening_id}/confirm", response_model=ConfirmOut)
async def confirm(
    screening_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConfirmOut:
    try:
        result = await schedule_service.confirm(session, screening_id, user.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ConfirmOut(
        screening_id=screening_id,
        state=result.state,
        place_in_queue=result.place_in_queue,
        confirmed=result.confirmed,
        capacity=result.capacity,
    )


@router.post("/screenings/{screening_id}/decline", response_model=ConfirmOut)
async def decline(
    screening_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConfirmOut:
    late_cancel_hours = int(await SettingsService(session).get("late_cancel_hours"))
    try:
        result = await schedule_service.cancel(
            session, screening_id, user.id, late_cancel_hours
        )
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ConfirmOut(
        screening_id=screening_id,
        state=result.state,
        place_in_queue=None,
        confirmed=result.confirmed,
        capacity=result.capacity,
    )


@router.get("/free-slots", response_model=list[SlotOut])
async def free_slots(
    admin: RequireModerator, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[SlotOut]:
    """Вечера, куда ещё можно поставить показ."""
    round_ = await _round_or_404(session)
    taken = set(
        (
            await session.execute(
                sa.select(Screening.slot_id).where(
                    Screening.round_id == round_.id, Screening.status != "cancelled"
                )
            )
        )
        .scalars()
        .all()
    )
    halls = {hall.id: hall for hall in (await session.execute(sa.select(Hall))).scalars()}
    slots = (
        (
            await session.execute(
                sa.select(Slot)
                .where(Slot.round_id == round_.id, Slot.blocked.is_(False))
                .order_by(Slot.starts_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        SlotOut(
            id=slot.id,
            starts_at=slot.starts_at,
            duration_min=slot.duration_min,
            blocked=slot.blocked,
            blocked_reason=slot.blocked_reason,
            hall_name=halls[slot.hall_id].name,
            hall_capacity=halls[slot.hall_id].capacity,
        )
        for slot in slots
        if slot.id not in taken
    ]
