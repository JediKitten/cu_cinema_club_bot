"""Админ-панель цикла: шорт-лист и вечера (§5, §9, §10)."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import RequireAdmin, RequireModerator
from app.db import get_session
from app.models import AutopilotProposal, Film, FilmVote, Hall, Round, ShortlistItem, Slot
from app.schemas import (
    BlockSlotIn,
    FilmBrief,
    OpenRoundIn,
    RoundLanguageIn,
    RoundOut,
    ShortlistAnnounceOut,
    ShortlistIn,
    ShortlistItemOut,
    SlotOut,
)
from app.services import autopilot
from app.services import rounds as rounds_service
from app.services.rounds import RoundError
from app.services.settings import SettingsService
from app.services.tmdb import poster_url

router = APIRouter(prefix="/api/admin/round", tags=["round"])


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


async def _serialize(session: AsyncSession, round_: Round) -> RoundOut:
    items = (
        await session.execute(
            sa.select(ShortlistItem, Film)
            .join(Film, Film.id == ShortlistItem.film_id)
            .where(ShortlistItem.round_id == round_.id)
            .order_by(ShortlistItem.position)
        )
    ).all()

    votes = dict(
        (
            await session.execute(
                sa.select(FilmVote.film_id, sa.func.count())
                .where(FilmVote.round_id == round_.id)
                .group_by(FilmVote.film_id)
            )
        ).all()
    )

    slots = (
        await session.execute(
            sa.select(Slot, Hall)
            .join(Hall, Hall.id == Slot.hall_id)
            .where(Slot.round_id == round_.id)
            .order_by(Slot.starts_at)
        )
    ).all()

    window = rounds_service.shortlist_window(
        round_.week_start, await SettingsService(session).all()
    )

    proposal = (
        await session.execute(
            sa.select(AutopilotProposal).where(
                AutopilotProposal.round_id == round_.id, AutopilotProposal.stage == 1
            )
        )
    ).scalar_one_or_none()

    return RoundOut(
        id=round_.id,
        week_start=round_.week_start,
        stage=round_.stage,
        low_activity=round_.low_activity,
        shortlist_locked_at=round_.shortlist_locked_at,
        published_at=round_.published_at,
        shortlist=[
            ShortlistItemOut(
                film_id=item.film_id,
                position=item.position,
                source=item.source,
                film=_brief(film),
                votes=votes.get(item.film_id, 0),
            )
            for item, film in items
        ],
        slots=[
            SlotOut(
                id=slot.id,
                starts_at=slot.starts_at,
                duration_min=slot.duration_min,
                blocked=slot.blocked,
                blocked_reason=slot.blocked_reason,
                hall_name=hall.name,
                hall_capacity=hall.capacity,
            )
            for slot, hall in slots
        ],
        autopilot_film_ids=list((proposal.payload or {}).get("film_ids", [])) if proposal else [],
        in_english=round_.in_english,
        shortlist_window_opens_at=window.opens_at,
        shortlist_autopilot_at=window.autopilot_at,
        shortlist_window_open=window.is_open,
    )


@router.get("", response_model=RoundOut | None)
async def current_round(
    admin: RequireModerator, session: Annotated[AsyncSession, Depends(get_session)]
) -> RoundOut | None:
    round_ = await rounds_service.active_round(session)
    return await _serialize(session, round_) if round_ else None


@router.post("", response_model=RoundOut, status_code=201)
async def open_round(
    body: OpenRoundIn,
    admin: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoundOut:
    try:
        round_ = await rounds_service.open_round(session, body.week_start, admin.id)
    except RoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    # Подсказку автопилота считаем сразу: админ должен видеть её рядом с рейтингами.
    await autopilot.propose_shortlist(session, round_)
    return await _serialize(session, round_)


@router.patch("/language", response_model=RoundOut)
async def set_language(
    body: RoundLanguageIn,
    admin: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoundOut:
    """«Эта неделя на английском».

    Ставится до голосования: человек решает, пойдёт ли он, ещё выбирая фильм,
    — поэтому пометка едет в том же сообщении, что зовёт голосовать.
    """
    round_ = await rounds_service.active_round(session)
    if round_ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активного цикла нет")
    await rounds_service.set_in_english(session, round_, body.in_english, admin.id)
    return await _serialize(session, round_)


@router.put("/shortlist", response_model=RoundOut)
async def set_shortlist(
    body: ShortlistIn,
    admin: RequireModerator,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoundOut:
    round_ = await rounds_service.active_round(session)
    if round_ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активного цикла нет")

    known = set(
        (
            await session.execute(sa.select(Film.id).where(Film.id.in_(body.film_ids)))
        ).scalars()
    )
    missing = [film_id for film_id in body.film_ids if film_id not in known]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Неизвестные фильмы: {missing}"
        )

    try:
        await rounds_service.set_shortlist(session, round_, body.film_ids, admin.id)
    except RoundError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _serialize(session, round_)


@router.post("/shortlist/publish", response_model=RoundOut)
async def publish_shortlist(
    admin: RequireModerator, session: Annotated[AsyncSession, Depends(get_session)]
) -> RoundOut:
    round_ = await rounds_service.active_round(session)
    if round_ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активного цикла нет")
    try:
        await rounds_service.publish_shortlist(session, round_, admin.id)
    except RoundError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _serialize(session, round_)


@router.post("/shortlist/announce", response_model=ShortlistAnnounceOut)
async def announce_shortlist(
    admin: RequireModerator, session: Annotated[AsyncSession, Depends(get_session)]
) -> ShortlistAnnounceOut:
    """Разослать поправленный шорт-лист всем, кому шло объявление о голосовании."""
    round_ = await rounds_service.active_round(session)
    if round_ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активного цикла нет")
    try:
        recipients = await rounds_service.announce_shortlist_update(session, round_, admin.id)
    except RoundError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ShortlistAnnounceOut(recipients=recipients)


@router.post("/slots/{slot_id}/block", response_model=RoundOut)
async def block_slot(
    slot_id: int,
    body: BlockSlotIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoundOut:
    """Блокировка вечеров — только админ (§9)."""
    try:
        await rounds_service.set_slot_blocked(session, slot_id, body.blocked, body.reason, admin.id)
    except RoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    round_ = await rounds_service.active_round(session)
    return await _serialize(session, round_)
