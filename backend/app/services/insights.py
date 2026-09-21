"""Статистика для администратора (§14, расширение по просьбе клуба).

Два экрана, которым нужны не агрегаты по клубу, а разрез по одному объекту:
карточка фильма («почему он в шорт-листе и что с ним было раньше») и карточка
сеанса («сколько придёт, кто в очереди, кто не пришёл»).

Ничего не материализуем: как и веса, всё считается из событий. Цифры на экране
всегда согласованы с тем, что сейчас в базе, и не расходятся с историей после
смены параметров §13.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attendance,
    Confirmation,
    Feedback,
    Film,
    FilmRating,
    Hall,
    Interest,
    Screening,
    ShortlistItem,
    Slot,
    User,
)
from app.models.enums import (
    ConfirmationState,
    DiscussionSkip,
    InterestKind,
    ScreeningStatus,
)
from app.services import ratings
from app.services.weights import (
    WeightParams,
    active_interest_clause,
    age_days_expr,
    interest_weight_expr,
)

# Сколько недель показывать в динамике интереса. Семестр — это примерно
# столько; более длинный хвост на телефоне всё равно нечитаем.
DYNAMICS_WEEKS = 16


@dataclass(slots=True)
class WeekPoint:
    week_start: str
    wishlist: int
    soon: int


@dataclass(slots=True)
class ScreeningRecord:
    screening_id: int
    starts_at: datetime | None
    status: str
    expected: int | None
    came: int
    rating: float | None


@dataclass(slots=True)
class FilmStats:
    film_id: int
    weight: float
    wishlist_count: int
    soon_count: int
    long_wait_count: int
    # Сколько раз фильм попадал в шорт-лист и так и не был назначен.
    shortlist_misses: int
    shortlist_hits: int
    internal_rating: float | None
    internal_votes: int
    dynamics: list[WeekPoint] = field(default_factory=list)
    history: list[ScreeningRecord] = field(default_factory=list)


@dataclass(slots=True)
class Person:
    user_id: int
    display_name: str
    detail: str | None = None


@dataclass(slots=True)
class ScreeningStats:
    screening_id: int
    starts_at: datetime
    capacity: int
    confirmed: int
    fill_rate: float
    waitlist: list[Person] = field(default_factory=list)
    attended: list[Person] = field(default_factory=list)
    no_shows: list[Person] = field(default_factory=list)
    cancelled: int = 0
    late_cancels: int = 0
    # Показ уже начался: до этого момента «не пришли» считать не из чего.
    started: bool = False
    # Кворум не набран, а до начала меньше early_warning_hours (§7).
    low_attendance_warning: bool = False
    min_attendance: int = 0
    film_rating: float | None = None
    film_rating_votes: int = 0
    # CSAT: как людям вечер целиком и обсуждение после. В рейтинг фильма
    # не входят — плохая проекция не должна топить хорошее кино.
    visit_rating: float | None = None
    visit_rating_votes: int = 0
    discussion_rating: float | None = None
    discussion_rating_votes: int = 0


async def shortlist_misses(
    session: AsyncSession, film_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """{film_id: (сколько раз попадал в шорт-лист без показа, сколько с показом)}.

    Попадание без показа — единственный сигнал, что фильм систематически
    проигрывает расстановку: по весам он проходит, а вечера ему не достаётся.
    """
    if not film_ids:
        return {}

    held = (
        sa.select(Screening.round_id, Screening.film_id)
        .where(Screening.status != ScreeningStatus.CANCELLED, Screening.round_id.is_not(None))
        .subquery()
    )
    rows = await session.execute(
        sa.select(
            ShortlistItem.film_id,
            sa.func.count().filter(held.c.film_id.is_(None)).label("missed"),
            sa.func.count().filter(held.c.film_id.is_not(None)).label("hit"),
        )
        .outerjoin(
            held,
            sa.and_(
                held.c.round_id == ShortlistItem.round_id,
                held.c.film_id == ShortlistItem.film_id,
            ),
        )
        .where(ShortlistItem.film_id.in_(film_ids))
        .group_by(ShortlistItem.film_id)
    )
    return {film_id: (missed, hit) for film_id, missed, hit in rows}


async def screening_history(
    session: AsyncSession, film_ids: list[int]
) -> dict[int, list[ScreeningRecord]]:
    """Прошлые показы фильма: дата, ожидаемая и фактическая явка, оценка."""
    if not film_ids:
        return {}

    rows = await session.execute(
        sa.select(
            Screening.film_id,
            Screening.id,
            Slot.starts_at,
            Screening.status,
            Screening.expected_attendance,
            sa.select(sa.func.count())
            .select_from(Attendance)
            .where(Attendance.screening_id == Screening.id)
            .scalar_subquery()
            .label("came"),
            sa.select(sa.func.avg(Feedback.film_rating))
            .where(Feedback.screening_id == Screening.id, Feedback.film_rating.is_not(None))
            .scalar_subquery()
            .label("rating"),
        )
        .join(Slot, Slot.id == Screening.slot_id)
        .where(Screening.film_id.in_(film_ids))
        .order_by(Slot.starts_at.desc())
    )
    history: dict[int, list[ScreeningRecord]] = {}
    for film_id, screening_id, starts_at, status, expected, came, rating in rows:
        history.setdefault(film_id, []).append(
            ScreeningRecord(
                screening_id=screening_id,
                starts_at=starts_at,
                status=status,
                expected=expected,
                came=came or 0,
                rating=round(float(rating), 2) if rating is not None else None,
            )
        )
    return history


async def interest_dynamics(
    session: AsyncSession, film_id: int, weeks: int = DYNAMICS_WEEKS
) -> list[WeekPoint]:
    """Сколько отметок каждого вида ставили на фильм по неделям.

    Считаем по моменту постановки отметки, а не по её нынешнему состоянию:
    вопрос «когда интерес рос» не имеет отношения к тому, жива ли отметка
    сегодня.
    """
    since = datetime.now(UTC) - timedelta(weeks=weeks)
    week = sa.func.date_trunc("week", Interest.created_at)
    rows = await session.execute(
        sa.select(
            week.label("week"),
            sa.func.count().filter(Interest.kind == InterestKind.WISHLIST),
            sa.func.count().filter(Interest.kind == InterestKind.SOON),
        )
        .where(Interest.film_id == film_id, Interest.created_at >= since)
        .group_by(week)
        .order_by(week)
    )
    return [
        WeekPoint(week_start=start.date().isoformat(), wishlist=wishlist, soon=soon)
        for start, wishlist, soon in rows
    ]


async def film_stats(
    session: AsyncSession, film_id: int, params: WeightParams, long_wait_days: int
) -> FilmStats | None:
    if await session.get(Film, film_id) is None:
        return None

    age = age_days_expr(Interest.created_at)
    counts = (
        await session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(interest_weight_expr(params)), 0.0),
                sa.func.count().filter(Interest.kind == InterestKind.WISHLIST),
                sa.func.count().filter(Interest.kind == InterestKind.SOON),
                sa.func.count(sa.distinct(Interest.user_id)).filter(age > long_wait_days),
            ).where(active_interest_clause(), Interest.film_id == film_id)
        )
    ).one()
    weight, wishlist_count, soon_count, long_wait_count = counts

    club = await ratings.summary(session, film_id)

    missed, hit = (await shortlist_misses(session, [film_id])).get(film_id, (0, 0))
    return FilmStats(
        film_id=film_id,
        weight=round(float(weight or 0.0), 3),
        wishlist_count=wishlist_count,
        soon_count=soon_count,
        long_wait_count=long_wait_count,
        shortlist_misses=missed,
        shortlist_hits=hit,
        internal_rating=club.average,
        internal_votes=club.votes,
        dynamics=await interest_dynamics(session, film_id),
        history=(await screening_history(session, [film_id])).get(film_id, []),
    )


async def _people(session: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = await session.execute(
        sa.select(User.id, User.display_name).where(User.id.in_(user_ids))
    )
    return dict(rows.all())


async def screening_stats(
    session: AsyncSession, screening_id: int, values: dict
) -> ScreeningStats | None:
    """Всё про один сеанс: до показа — кто придёт, после — кто пришёл."""
    screening = await session.get(Screening, screening_id)
    if screening is None:
        return None
    slot = await session.get(Slot, screening.slot_id)
    hall = await session.get(Hall, slot.hall_id)

    confirmations = (
        await session.execute(
            sa.select(Confirmation)
            .where(Confirmation.screening_id == screening_id)
            .order_by(Confirmation.created_at)
        )
    ).scalars().all()

    confirmed = [c for c in confirmations if c.state == ConfirmationState.CONFIRMED]
    waitlist = [c for c in confirmations if c.state == ConfirmationState.WAITLIST]
    cancelled = [c for c in confirmations if c.state == ConfirmationState.CANCELLED]

    attendance = (
        await session.execute(
            sa.select(Attendance)
            .where(Attendance.screening_id == screening_id)
            .order_by(Attendance.marked_at)
        )
    ).scalars().all()

    came_ids = {a.user_id for a in attendance}
    names = await _people(
        session,
        [c.user_id for c in confirmations] + [a.user_id for a in attendance],
    )

    def person(user_id: int, detail: str | None = None) -> Person:
        return Person(user_id=user_id, display_name=names.get(user_id, "—"), detail=detail)

    capacity = hall.capacity if hall else 0
    minimum = int(values["min_attendance"])
    hours_left = (slot.starts_at - datetime.now(UTC)).total_seconds() / 3600
    # До начала «не пришли» не существует: отмечаться ещё нельзя, и все, кто
    # подтвердил, попали бы в список неявившихся. Проведённый показ считаем
    # начавшимся независимо от часов: статус здесь важнее календаря.
    started = hours_left <= 0 or screening.status == ScreeningStatus.COMPLETED

    film_rating = (
        await session.execute(
            sa.select(sa.func.avg(Feedback.film_rating), sa.func.count(Feedback.film_rating)).where(
                Feedback.screening_id == screening_id, Feedback.film_rating.is_not(None)
            )
        )
    ).one()

    # Впечатление от вечера и от обсуждения — отдельные числа и в рейтинг
    # фильма не входят (§8).
    visit_avg, visit_votes, discussion_avg, discussion_votes = (
        await session.execute(
            sa.select(
                sa.func.avg(Feedback.visit_rating),
                sa.func.count(Feedback.visit_rating),
                sa.func.avg(Feedback.discussion_rating),
                sa.func.count(Feedback.discussion_rating),
            ).where(Feedback.screening_id == screening_id)
        )
    ).one()

    return ScreeningStats(
        screening_id=screening_id,
        starts_at=slot.starts_at,
        capacity=capacity,
        confirmed=len(confirmed),
        fill_rate=round(len(confirmed) / capacity * 100, 1) if capacity else 0.0,
        waitlist=[person(c.user_id, f"в очереди {index + 1}") for index, c in enumerate(waitlist)],
        attended=[person(a.user_id, a.method) for a in attendance],
        # Подтвердил и не пришёл. Отменившие сюда не попадают: они предупредили.
        no_shows=(
            [person(c.user_id) for c in confirmed if c.user_id not in came_ids]
            if started
            else []
        ),
        started=started,
        cancelled=len(cancelled),
        late_cancels=sum(1 for c in cancelled if c.was_late_cancel),
        low_attendance_warning=(
            screening.status == ScreeningStatus.SCHEDULED
            and 0 < hours_left <= int(values["early_warning_hours"])
            and len(confirmed) < minimum
        ),
        min_attendance=minimum,
        film_rating=round(float(film_rating[0]), 2) if film_rating[1] else None,
        film_rating_votes=film_rating[1],
        visit_rating=round(float(visit_avg), 2) if visit_votes else None,
        visit_rating_votes=visit_votes,
        discussion_rating=round(float(discussion_avg), 2) if discussion_votes else None,
        discussion_rating_votes=discussion_votes,
    )


@dataclass(slots=True)
class SurveyAnswer:
    """Ответ одного человека на опрос после показа."""

    user_id: int
    display_name: str
    visit: int | None
    film: int | None
    discussion: int | None
    discussion_skip: str | None
    comment: str | None
    answered_at: datetime


@dataclass(slots=True)
class SurveyResult:
    """Опрос по одному показу: цифры для отчёта и ответы поимённо.

    Поимённо — потому что средним по десяти ответам отчитаться можно, а понять
    нельзя: одна тройка с припиской «звук фонил» говорит больше, чем сама
    четвёрка. Клуб маленький, и анонимности здесь никто не обещал.
    """

    screening_id: int
    starts_at: datetime
    title: str
    attended: int
    answered: int
    visit_avg: float | None
    film_avg: float | None
    discussion_avg: float | None
    # Сколько ответили «не был» и «затрудняюсь ответить»: без них средняя
    # по обсуждению выглядит увереннее, чем есть.
    discussion_absent: int
    discussion_unsure: int
    answers: list[SurveyAnswer]


def _avg(values: list[int]) -> float | None:
    # Полубаллы приводим к звёздам сразу: в отчёт идут они, а не внутренняя шкала.
    return round(sum(values) / len(values) / 2, 2) if values else None


async def surveys(session: AsyncSession, limit: int = 20) -> list[SurveyResult]:
    """Опросы по прошедшим показам, свежие сверху."""
    rows = (
        await session.execute(
            sa.select(Screening, Slot, Film)
            .join(Slot, Slot.id == Screening.slot_id)
            .outerjoin(Film, Film.id == Screening.film_id)
            # По статусу, а не по времени: завершёнными показы делает та же
            # фоновая задача, что наполняет «Что уже смотрели», и два списка
            # должны говорить об одном и том же.
            .where(Screening.status == ScreeningStatus.COMPLETED)
            .order_by(Slot.starts_at.desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    ids = [screening.id for screening, _, _ in rows]
    # Оценка фильма берётся из каталога, если в самой форме её не спрашивали:
    # у фильма она одна, и человеку, поставившему её раньше, второй раз
    # вопрос не показывают — но в отчёте она должна быть.
    feedback: dict[int, list[tuple[Feedback, str, int | None]]] = {}
    for item, name, catalogue in await session.execute(
        sa.select(Feedback, User.display_name, FilmRating.score)
        .join(User, User.id == Feedback.user_id)
        .outerjoin(
            FilmRating,
            sa.and_(
                FilmRating.user_id == Feedback.user_id,
                FilmRating.film_id == Feedback.film_id,
            ),
        )
        .where(Feedback.screening_id.in_(ids))
        .order_by(Feedback.created_at)
    ):
        feedback.setdefault(item.screening_id, []).append((item, name, catalogue))

    came = dict(
        (
            await session.execute(
                sa.select(Attendance.screening_id, sa.func.count())
                .where(Attendance.screening_id.in_(ids))
                .group_by(Attendance.screening_id)
            )
        ).all()
    )

    out: list[SurveyResult] = []
    for screening, slot, film in rows:
        items = feedback.get(screening.id, [])
        out.append(
            SurveyResult(
                screening_id=screening.id,
                starts_at=slot.starts_at,
                title=film.title_ru if film else (screening.title or "Событие клуба"),
                attended=came.get(screening.id, 0),
                answered=len(items),
                visit_avg=_avg([i.visit_rating for i, _, _ in items if i.visit_rating]),
                film_avg=_avg(
                    [rating for i, _, c in items if (rating := i.film_rating or c)]
                ),
                discussion_avg=_avg(
                    [i.discussion_rating for i, _, _ in items if i.discussion_rating]
                ),
                discussion_absent=sum(
                    1 for i, _, _ in items if i.discussion_skip == DiscussionSkip.ABSENT
                ),
                discussion_unsure=sum(
                    1 for i, _, _ in items if i.discussion_skip == DiscussionSkip.UNSURE
                ),
                answers=[
                    SurveyAnswer(
                        user_id=item.user_id,
                        display_name=name,
                        visit=item.visit_rating,
                        film=item.film_rating or catalogue,
                        discussion=item.discussion_rating,
                        discussion_skip=item.discussion_skip,
                        comment=item.review_text,
                        answered_at=item.created_at,
                    )
                    for item, name, catalogue in items
                ],
            )
        )
    return out
