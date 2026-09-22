"""Этап 3 — расписание и подтверждения (§7)."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireAdmin, RequireModerator
from app.db import get_session
from app.models import (
    Attendance,
    Confirmation,
    Film,
    FilmVote,
    Hall,
    Round,
    Screening,
    Slot,
)
from app.models.enums import ConfirmationState, RoundStage, ScreeningStatus
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


async def _week_bounds(session: AsyncSession, week: date) -> tuple[datetime, datetime]:
    """Границы недели в UTC.

    Неделя задана датой понедельника в локальной зоне вуза, а времена слотов
    хранятся в UTC — поэтому переводим явно, а не прибавляем смещение.
    """
    tz = ZoneInfo(str(await SettingsService(session).get("display_timezone")))
    start = datetime.combine(week, time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=7)).astimezone(UTC)


async def _manual_rows(session: AsyncSession, week: date):
    """Ручные события этой недели. Они вне цикла, поэтому подтягиваются отдельно."""
    start, end = await _week_bounds(session, week)
    # Фильм — тем же запросом: у события его может не быть («ждите анонса»),
    # поэтому внешнее соединение, а не отдельный запрос на каждую строку.
    rows = await session.execute(
        sa.select(Screening, Film, Slot)
        .join(Slot, Slot.id == Screening.slot_id)
        .outerjoin(Film, Film.id == Screening.film_id)
        .where(
            Screening.is_manual.is_(True),
            Screening.status != ScreeningStatus.CANCELLED,
            Slot.starts_at >= start,
            Slot.starts_at < end,
        )
        .order_by(Slot.starts_at)
    )
    return [(event, film, slot) for event, film, slot in rows]


async def _neighbours(session: AsyncSession, week: date) -> tuple[bool, bool]:
    """Есть ли что показать в соседних неделях — по ним рисуются стрелки.

    Считаем и циклы, и ручные события: неделя с одним лишь анонсом тоже стоит
    того, чтобы на неё можно было пролистать.
    """
    start, end = await _week_bounds(session, week)

    async def any_screening(before: bool) -> bool:
        condition = Slot.starts_at < start if before else Slot.starts_at >= end
        found = await session.scalar(
            sa.select(Screening.id)
            .join(Slot, Slot.id == Screening.slot_id)
            .where(Screening.status != ScreeningStatus.CANCELLED, condition)
            .limit(1)
        )
        return found is not None

    async def any_round(before: bool) -> bool:
        condition = Round.week_start < week if before else Round.week_start > week
        found = await session.scalar(sa.select(Round.id).where(condition).limit(1))
        return found is not None

    return (
        await any_screening(True) or await any_round(True),
        await any_screening(False) or await any_round(False),
    )


async def _round_or_404(session: AsyncSession) -> Round:
    round_ = await rounds_service.active_round(session)
    if round_ is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активного цикла нет")
    return round_


async def _screening_week(session: AsyncSession, screening_id: int) -> date:
    """Неделя, которой принадлежит показ.

    Правят и показы идущей недели, а готовится в это время уже следующая —
    возвращать в ответ её расписание значило бы показать админу не тот экран,
    на котором он только что нажал кнопку.
    """
    starts_at = await session.scalar(
        sa.select(Slot.starts_at)
        .join(Screening, Screening.slot_id == Slot.id)
        .where(Screening.id == screening_id)
    )
    if starts_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Показ не найден")
    tz = ZoneInfo(str(await SettingsService(session).get("display_timezone")))
    return rounds_service.week_start_for(starts_at.astimezone(tz).date())


async def _to_out(
    session: AsyncSession, rows: list, round_: Round | None, user_id: int
) -> list[ScreeningOut]:
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
    voted_films: set[int] = set()
    if round_ is not None:
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
    came = set(
        (
            await session.execute(
                sa.select(Attendance.screening_id).where(
                    Attendance.screening_id.in_(ids), Attendance.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
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
                in_english=screening.in_english,
                # Ссылку отдаём всем: увидит её только записавшийся, но
                # прятать на сервере нечего — это публичная регистрация.
                registration_url=screening.registration_url,
                note=screening.note,
                my_state=confirmation.state if confirmation else None,
                my_place_in_queue=place,
                confirmed=counts.get(screening.id, 0),
                capacity=hall.capacity,
                # У ручного события фильма может не быть — голосовать было не за что.
                invited=film is not None and film.id in voted_films,
                i_attended=screening.id in came,
            )
        )

    return out


async def _week_view(
    session: AsyncSession, week: date, user, *, force_show: bool = False
) -> ScheduleOut:
    """Расписание одной недели — общий сбор для всех, кто его отдаёт.

    force_show нужен админским действиям: после расстановки показ должен быть
    виден составителю сразу, не дожидаясь публикации.
    """
    round_ = (
        await session.execute(sa.select(Round).where(Round.week_start == week))
    ).scalar_one_or_none()

    unpublished = round_ is not None and round_.stage in (
        RoundStage.COLLECTING,
        RoundStage.SHORTLIST_REVIEW,
        RoundStage.SLOT_VOTING,
    )
    hide_round = unpublished and user.role.rank < 1 and not force_show  # ниже модератора

    rows = []
    if round_ is not None and not hide_round:
        rows += await schedule_service.screenings_of(session, round_)
    rows += await _manual_rows(session, week)
    rows.sort(key=lambda item: item[2].starts_at)

    has_prev, has_next = await _neighbours(session, week)
    voting_week = await _voting_week(session)
    return ScheduleOut(
        voting_week=voting_week if voting_week != week else None,
        round_id=round_.id if round_ else 0,
        week_start=week,
        stage=round_.stage if round_ else "collecting",
        published=round_ is not None
        and round_.stage in (RoundStage.PUBLISHED, RoundStage.RUNNING, RoundStage.CLOSED),
        screenings=await _to_out(session, rows, round_, user.id),
        has_prev=has_prev,
        has_next=has_next,
    )


@router.get("", response_model=ScheduleOut)
async def schedule(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    week: date | None = None,
) -> ScheduleOut:
    """Расписание недели. Без параметра — та неделя, что сейчас в работе.

    Показы цикла до публикации видны только тем, кто его составляет. Ручные
    события — всем и всегда: они анонсируются отдельно от цикла, и прятать их
    за его этапом значило бы не показать анонс вовсе.
    """
    week = _monday(week) if week else await _default_week(session)
    return await _week_view(session, week, user)


# Суббота: с неё неделя считается прожитой и расписание смотрит вперёд.
SATURDAY = 5
DAYS_IN_WEEK = 7


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def default_week(today: date) -> date:
    """Правило выбора недели — отдельно от запроса, чтобы его можно было
    проверить на конкретном дне, а не на том, который случился при прогоне."""
    current = _monday(today)
    return current + timedelta(days=DAYS_IN_WEEK) if today.weekday() >= SATURDAY else current


async def _default_week(session: AsyncSession) -> date:
    """Какую неделю показываем при открытии.

    До пятницы включительно — текущую: на ней ещё могут быть показы, и человек
    открывает расписание ради них. В субботу и воскресенье неделя уже прожита,
    и показывать её огрызок незачем — переходим к следующей, даже если она
    пустая: как раз в эти дни идёт голосование, и пустая неделя со словами
    «выберите фильм» полезнее доживающей.

    Неделя активного цикла тут не годится: он готовится к следующей, и в среду
    человек увидел бы пустой экран вместо сегодняшнего показа.
    """
    tz = ZoneInfo(str(await SettingsService(session).get("display_timezone")))
    # День считаем по зоне вуза, а не по часам сервера: в воскресенье ночью
    # по Москве в UTC ещё суббота, и «следующая неделя» разъехалась бы.
    return default_week(datetime.now(tz).date())


async def _voting_week(session: AsyncSession) -> date | None:
    """Неделя, на которую сейчас идёт голосование.

    Нужна, чтобы с текущей недели вести туда: голосование — единственное,
    что требует действия, и прятать его за листанием неправильно.
    """
    round_ = await rounds_service.active_round(session)
    if round_ is not None and round_.stage == RoundStage.SLOT_VOTING:
        return round_.week_start
    return None


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
    return await _week_view(session, round_.week_start, admin, force_show=True)


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
    return await _week_view(session, round_.week_start, admin, force_show=True)


@router.post("/publish", response_model=ScheduleOut)
async def publish(
    admin: RequireModerator, session: Annotated[AsyncSession, Depends(get_session)]
) -> ScheduleOut:
    round_ = await _round_or_404(session)
    try:
        await schedule_service.publish_schedule(session, round_, admin.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _week_view(session, round_.week_start, admin, force_show=True)


@router.post("/screenings/{screening_id}/move", response_model=ScheduleOut)
async def move(
    screening_id: int,
    body: MoveIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScheduleOut:
    """Правка опубликованного расписания — только админ (§9)."""
    try:
        await schedule_service.move_screening(session, screening_id, body.slot_id, admin.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    week = await _screening_week(session, screening_id)
    return await _week_view(session, week, admin, force_show=True)


@router.post("/screenings/{screening_id}/cancel", response_model=ScheduleOut)
async def cancel_screening(
    screening_id: int,
    body: CancelIn,
    admin: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScheduleOut:
    week = await _screening_week(session, screening_id)
    try:
        await schedule_service.cancel_screening(session, screening_id, body.reason, admin.id)
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _week_view(session, week, admin, force_show=True)


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
