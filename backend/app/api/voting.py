"""Этап 2 — голосование за фильмы и вечера (§6)."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireModerator
from app.db import get_session
from app.models import AutopilotProposal, Film, Hall, Round, Screening, Slot
from app.models.enums import ScreeningStatus
from app.schemas import (
    Assignment,
    AvailabilityIn,
    BallotOut,
    FilmBrief,
    MatrixCell,
    MatrixOut,
    SlotOut,
    VotesIn,
)
from app.services import rounds as rounds_service
from app.services import voting
from app.services.tmdb import poster_url
from app.services.voting import VotingError

router = APIRouter(prefix="/api/round", tags=["voting"])


def _brief(film: Film) -> FilmBrief:
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


async def _slot_out(session: AsyncSession, slots: list[Slot]) -> list[SlotOut]:
    halls = {hall.id: hall for hall in (await session.execute(sa.select(Hall))).scalars()}
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
    ]


async def _open_round(session: AsyncSession) -> Round:
    try:
        return voting.ensure_open(await rounds_service.active_round(session))
    except VotingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


async def _ballot(session: AsyncSession, round_: Round, user_id: int) -> BallotOut:
    films = await voting.shortlist_films(session, round_)
    slots = await voting.open_slots(session, round_)
    return BallotOut(
        round_id=round_.id,
        week_start=round_.week_start,
        films=[_brief(film) for film in films],
        slots=await _slot_out(session, slots),
        my_film_ids=await voting.my_votes(session, round_, user_id),
        my_slot_ids=await voting.my_availability(session, round_, user_id),
        in_english=round_.in_english,
    )


@router.get("/ballot", response_model=BallotOut)
async def ballot(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> BallotOut:
    return await _ballot(session, await _open_round(session), user.id)


@router.put("/votes", response_model=BallotOut)
async def set_votes(
    body: VotesIn, user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> BallotOut:
    round_ = await _open_round(session)
    try:
        await voting.set_votes(session, round_, user.id, body.film_ids)
    except VotingError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await _ballot(session, round_, user.id)


@router.put("/availability", response_model=BallotOut)
async def set_availability(
    body: AvailabilityIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BallotOut:
    round_ = await _open_round(session)
    try:
        await voting.set_availability(session, round_, user.id, body.slot_ids)
    except VotingError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await _ballot(session, round_, user.id)


@router.get("/matrix", response_model=MatrixOut, tags=["round"])
async def matrix(
    admin: RequireModerator, session: Annotated[AsyncSession, Depends(get_session)]
) -> MatrixOut:
    """Матрица «фильм × слот» — то, по чему администратор расставляет показы."""
    round_ = await rounds_service.active_round(session)
    if round_ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активного цикла нет")

    built = await voting.build_matrix(session, round_)
    films = await voting.shortlist_films(session, round_)
    slots = await voting.open_slots(session, round_)

    blocked = (
        await session.execute(
            sa.select(Slot)
            .where(Slot.round_id == round_.id, Slot.blocked.is_(True))
            .order_by(Slot.starts_at)
        )
    ).scalars().all()

    # Теневой режим: решение автопилота лежит рядом с ручным, чтобы видеть,
    # чем расстановка отличается и во сколько человек обходится (§5).
    proposal = (
        await session.execute(
            sa.select(AutopilotProposal).where(
                AutopilotProposal.round_id == round_.id, AutopilotProposal.stage == 2
            )
        )
    ).scalar_one_or_none()
    autopilot = [
        Assignment(**item) for item in ((proposal.payload if proposal else {}) or {}).get(
            "assignments", []
        )
    ]

    placed = (
        await session.execute(
            sa.select(Screening).where(
                Screening.round_id == round_.id,
                Screening.status != ScreeningStatus.CANCELLED,
            )
        )
    ).scalars().all()
    manual = [
        Assignment(
            film_id=screening.film_id,
            slot_id=screening.slot_id,
            # Ожидание берём из матрицы, а не из снимка: параметры могли
            # поменяться, и два числа на экране разъехались бы.
            expected=built.cell(screening.film_id, screening.slot_id),
        )
        for screening in placed
        if screening.film_id is not None
    ]

    return MatrixOut(
        films=[_brief(film) for film in films],
        slots=await _slot_out(session, slots),
        cells=[
            MatrixCell(film_id=film_id, slot_id=slot_id, count=count)
            for (film_id, slot_id), count in built.cells.items()
        ],
        film_votes=built.film_votes,
        slot_free=built.slot_free,
        voters_without_evening=built.voters_without_evening,
        blocked_slots=await _slot_out(session, list(blocked)),
        autopilot=autopilot,
        manual=manual,
        autopilot_expected=sum(item.expected for item in autopilot),
        manual_expected=sum(item.expected for item in manual),
    )
