"""Турниры — голосование сеткой (расширение по просьбе клуба)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireAdmin
from app.db import get_session
from app.models import Tournament
from app.models.enums import TournamentStatus
from app.schemas import (
    TournamentBrief,
    TournamentIn,
    TournamentMatchOut,
    TournamentOptionOut,
    TournamentOptionsIn,
    TournamentOut,
    TournamentRoundOut,
    TournamentVoteIn,
)
from app.services import tournaments
from app.services.tournaments import TournamentError

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])


def _option(option: tournaments.OptionView | None) -> TournamentOptionOut | None:
    if option is None:
        return None
    return TournamentOptionOut(
        id=option.id,
        seed=option.seed,
        title=option.title,
        subtitle=option.subtitle,
        image_url=option.image_url,
        film_id=option.film_id,
    )


def _out(view: tournaments.TournamentView) -> TournamentOut:
    return TournamentOut(
        id=view.id,
        title=view.title,
        description=view.description,
        status=view.status,
        current_round=view.current_round,
        stage_hours=view.stage_hours,
        options_count=view.options_count,
        started_at=view.started_at,
        finished_at=view.finished_at,
        winner=_option(view.winner),
        rounds=[
            TournamentRoundOut(
                round_no=round_.round_no,
                name=round_.name,
                closed=round_.closed,
                matches=[
                    TournamentMatchOut(
                        id=match.id,
                        round_no=match.round_no,
                        position=match.position,
                        option_a=_option(match.option_a),
                        option_b=_option(match.option_b),
                        opens_at=match.opens_at,
                        closes_at=match.closes_at,
                        my_option_id=match.my_option_id,
                        votes_a=match.votes_a,
                        votes_b=match.votes_b,
                        winner_option_id=match.winner_option_id,
                    )
                    for match in round_.matches
                ],
            )
            for round_ in view.rounds
        ],
        left_to_vote=view.left_to_vote,
        closes_at=view.closes_at,
    )


def _brief(tournament: Tournament) -> TournamentBrief:
    return TournamentBrief(
        id=tournament.id,
        title=tournament.title,
        status=tournament.status,
        started_at=tournament.started_at,
        finished_at=tournament.finished_at,
    )


async def _found(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await session.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Турнир не найден")
    return tournament


@router.get("/current")
async def current(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TournamentOut | None:
    """Идущий турнир целиком — на нём держится и плашка, и экран сетки."""
    tournament = await tournaments.active(session)
    if tournament is None:
        return None
    return _out(await tournaments.view(session, tournament, user.id))


@router.get("")
async def archive(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TournamentBrief]:
    """Что уже отыграли. Черновики видит только админ — их ещё нет для клуба."""
    statuses = [TournamentStatus.RUNNING, TournamentStatus.FINISHED]
    if user.role.rank >= 2:  # админ и выше
        statuses.append(TournamentStatus.DRAFT)
    return [_brief(item) for item in await tournaments.listing(session, statuses)]


@router.get("/{tournament_id}")
async def one(
    tournament_id: int,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TournamentOut:
    tournament = await _found(session, tournament_id)
    return _out(await tournaments.view(session, tournament, user.id))


@router.post("/{tournament_id}/vote")
async def vote(
    tournament_id: int,
    body: TournamentVoteIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TournamentOut:
    tournament = await _found(session, tournament_id)
    try:
        await tournaments.vote(session, tournament, body.match_id, user.id, body.option_id)
    except TournamentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _out(await tournaments.view(session, tournament, user.id))


# --- Админское -------------------------------------------------------------


@router.post("")
async def create(
    body: TournamentIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TournamentOut:
    try:
        tournament = await tournaments.create(session, admin.id, body.title, body.description)
    except TournamentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _out(await tournaments.view(session, tournament, admin.id))


@router.put("/{tournament_id}/options")
async def set_options(
    tournament_id: int,
    body: TournamentOptionsIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TournamentOut:
    tournament = await _found(session, tournament_id)
    try:
        await tournaments.set_options(
            session,
            tournament,
            [
                tournaments.OptionIn(
                    title=item.title,
                    subtitle=item.subtitle,
                    image_url=item.image_url,
                    film_id=item.film_id,
                )
                for item in body.options
            ],
        )
    except TournamentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _out(await tournaments.view(session, tournament, admin.id))


@router.post("/{tournament_id}/start")
async def start(
    tournament_id: int,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TournamentOut:
    tournament = await _found(session, tournament_id)
    try:
        await tournaments.start(session, tournament, admin.id)
    except TournamentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _out(await tournaments.view(session, tournament, admin.id))


@router.post("/{tournament_id}/cancel")
async def cancel(
    tournament_id: int,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TournamentOut:
    tournament = await _found(session, tournament_id)
    try:
        await tournaments.cancel(session, tournament, admin.id)
    except TournamentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _out(await tournaments.view(session, tournament, admin.id))
