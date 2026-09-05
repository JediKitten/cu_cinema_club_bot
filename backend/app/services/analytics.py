"""Аналитика (§14).

Главное здесь — воронка: отметил интерес → проголосовал → подтвердил → пришёл.
Каждый переход диагностирует свою проблему, поэтому важны именно переходы,
а не абсолютные числа: провал между голосованием и подтверждением означает
неудобные слоты, между подтверждением и явкой — что подтверждение не
воспринимают всерьёз.
"""

from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attendance,
    Confirmation,
    Feedback,
    Film,
    FilmVote,
    Hall,
    Interest,
    Round,
    Screening,
    Slot,
)
from app.models.enums import ConfirmationState, RoundStage, ScreeningStatus

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


@dataclass(slots=True)
class Funnel:
    week_start: date
    stage: str
    interested: int
    voted: int
    confirmed: int
    attended: int

    def as_dict(self) -> dict:
        return {
            "week_start": self.week_start.isoformat(),
            "stage": self.stage,
            "interested": self.interested,
            "voted": self.voted,
            "confirmed": self.confirmed,
            "attended": self.attended,
        }


@dataclass(slots=True)
class Overview:
    rounds: int
    screenings_held: int
    screenings_cancelled: int
    average_attendance: float
    hall_fill_rate: float
    active_users: int
    no_show_rate: float
    late_cancels: int
    by_weekday: dict[str, float] = field(default_factory=dict)
    long_wait_films: list[dict] = field(default_factory=list)


async def funnel(session: AsyncSession, limit: int = 8) -> list[Funnel]:
    """Воронка по неделям, свежие первыми."""
    rounds = (
        (
            await session.execute(
                sa.select(Round).order_by(Round.week_start.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )

    result = []
    for round_ in rounds:
        # «Отметил интерес» считаем по живым отметкам на момент запроса: точный
        # срез прошлого потребовал бы истории, которой мы намеренно не ведём.
        interested = (
            await session.scalar(
                sa.select(sa.func.count(sa.distinct(Interest.user_id))).where(
                    Interest.revoked_at.is_(None)
                )
            )
            or 0
        )
        voted = (
            await session.scalar(
                sa.select(sa.func.count(sa.distinct(FilmVote.user_id))).where(
                    FilmVote.round_id == round_.id
                )
            )
            or 0
        )
        confirmed = (
            await session.scalar(
                sa.select(sa.func.count(sa.distinct(Confirmation.user_id)))
                .select_from(Confirmation)
                .join(Screening, Screening.id == Confirmation.screening_id)
                .where(
                    Screening.round_id == round_.id,
                    Confirmation.state == ConfirmationState.CONFIRMED,
                )
            )
            or 0
        )
        attended = (
            await session.scalar(
                sa.select(sa.func.count(sa.distinct(Attendance.user_id)))
                .select_from(Attendance)
                .join(Screening, Screening.id == Attendance.screening_id)
                .where(Screening.round_id == round_.id)
            )
            or 0
        )
        result.append(
            Funnel(
                week_start=round_.week_start,
                stage=round_.stage,
                interested=interested,
                voted=voted,
                confirmed=confirmed,
                attended=attended,
            )
        )
    return result


async def overview(session: AsyncSession, long_wait_days: int) -> Overview:
    rounds = await session.scalar(sa.select(sa.func.count()).select_from(Round)) or 0

    held = (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Screening)
            .where(Screening.status == ScreeningStatus.COMPLETED)
        )
        or 0
    )
    cancelled = (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Screening)
            .where(Screening.status == ScreeningStatus.CANCELLED)
        )
        or 0
    )

    # Средняя явка — по показам, на которых кто-то был: показы без единой
    # отметки чаще означают, что код просто не показали, а не пустой зал.
    per_screening = (
        await session.execute(
            sa.select(Attendance.screening_id, sa.func.count()).group_by(
                Attendance.screening_id
            )
        )
    ).all()
    counts = [count for _, count in per_screening]
    average = round(sum(counts) / len(counts), 1) if counts else 0.0

    # Доля заполнения зала. Берём наибольшую вместимость: при одном зале это
    # он и есть, а при нескольких — верхняя граница, что честнее среднего.
    hall_capacity = await session.scalar(sa.select(sa.func.max(Hall.capacity))) or 0
    fill = round(average / hall_capacity * 100, 1) if counts and hall_capacity else 0.0

    active_users = (
        await session.scalar(
            sa.select(sa.func.count(sa.distinct(Interest.user_id))).where(
                Interest.revoked_at.is_(None)
            )
        )
        or 0
    )

    # Подтвердил и не пришёл — доля от всех подтверждений на прошедших показах.
    confirmed_total = (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Confirmation)
            .join(Screening, Screening.id == Confirmation.screening_id)
            .where(
                Confirmation.state == ConfirmationState.CONFIRMED,
                Screening.status == ScreeningStatus.COMPLETED,
            )
        )
        or 0
    )
    came = (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Attendance)
            .join(Screening, Screening.id == Attendance.screening_id)
            .where(Screening.status == ScreeningStatus.COMPLETED)
        )
        or 0
    )
    no_show = (
        round((confirmed_total - came) / confirmed_total * 100, 1)
        if confirmed_total
        else 0.0
    )

    late_cancels = (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Confirmation)
            .where(Confirmation.was_late_cancel.is_(True))
        )
        or 0
    )

    # Явка по дням недели: подсказывает, какие вечера вообще работают.
    by_weekday: dict[str, float] = {}
    rows = await session.execute(
        sa.select(Slot.starts_at, sa.func.count(Attendance.id))
        .select_from(Screening)
        .join(Slot, Slot.id == Screening.slot_id)
        .outerjoin(Attendance, Attendance.screening_id == Screening.id)
        .where(Screening.status == ScreeningStatus.COMPLETED)
        .group_by(Screening.id, Slot.starts_at)
    )
    buckets: dict[int, list[int]] = {}
    for starts_at, count in rows:
        buckets.setdefault(starts_at.weekday(), []).append(count)
    for weekday, values in sorted(buckets.items()):
        by_weekday[WEEKDAYS[weekday]] = round(sum(values) / len(values), 1)

    return Overview(
        rounds=rounds,
        screenings_held=held,
        screenings_cancelled=cancelled,
        average_attendance=average,
        hall_fill_rate=fill,
        active_users=active_users,
        no_show_rate=no_show,
        late_cancels=late_cancels,
        by_weekday=by_weekday,
        long_wait_films=await long_waiting(session, long_wait_days),
    )


async def long_waiting(session: AsyncSession, long_wait_days: int, limit: int = 10) -> list[dict]:
    """Фильмы, которых дольше всего ждут (§14)."""
    age_days = sa.extract("epoch", sa.func.now() - Interest.created_at) / 86400.0
    rows = await session.execute(
        sa.select(
            Film.title_ru,
            Film.year,
            sa.func.count(sa.distinct(Interest.user_id)).label("waiting"),
            sa.func.max(age_days).label("oldest"),
        )
        .join(Interest, Interest.film_id == Film.id)
        .where(Interest.revoked_at.is_(None), age_days > long_wait_days)
        .group_by(Film.id, Film.title_ru, Film.year)
        .order_by(sa.desc("waiting"), sa.desc("oldest"))
        .limit(limit)
    )
    return [
        {"title": title, "year": year, "waiting": waiting, "days": int(oldest)}
        for title, year, waiting, oldest in rows
    ]


async def top_rated(session: AsyncSession, min_votes: int, limit: int = 10) -> list[dict]:
    """Внутренний рейтинг клуба — только фильмы с достаточным числом оценок (§11)."""
    rows = await session.execute(
        sa.select(
            Film.title_ru,
            Film.year,
            sa.func.avg(Feedback.film_rating).label("rating"),
            sa.func.count(Feedback.film_rating).label("votes"),
        )
        .join(Feedback, Feedback.film_id == Film.id)
        .where(Feedback.film_rating.is_not(None))
        .group_by(Film.id, Film.title_ru, Film.year)
        .having(sa.func.count(Feedback.film_rating) >= min_votes)
        .order_by(sa.desc("rating"))
        .limit(limit)
    )
    return [
        {"title": title, "year": year, "rating": round(float(rating), 2), "votes": votes}
        for title, year, rating, votes in rows
    ]


async def past_screenings(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Календарь прошедших показов (§18, пункт 10).

    Только состоявшиеся: отменённый показ никто не смотрел, и во вкладке
    «Что уже смотрели» он лишь путает. Отмены видны в аналитике отдельно.
    """
    rows = await session.execute(
        sa.select(
            Screening.id,
            Film.id.label("film_id"),
            Film.title_ru,
            Film.year,
            Film.poster_path,
            Slot.starts_at,
            Screening.status,
            Screening.expected_attendance,
            sa.func.count(Attendance.id).label("came"),
            sa.func.avg(Feedback.film_rating).label("rating"),
        )
        .join(Film, Film.id == Screening.film_id)
        .join(Slot, Slot.id == Screening.slot_id)
        .outerjoin(Attendance, Attendance.screening_id == Screening.id)
        .outerjoin(Feedback, Feedback.screening_id == Screening.id)
        .where(Screening.status == ScreeningStatus.COMPLETED)
        .group_by(Screening.id, Film.id, Film.title_ru, Film.year, Film.poster_path, Slot.starts_at)
        .order_by(Slot.starts_at.desc())
        .limit(limit)
    )
    return [
        {
            "screening_id": sid,
            "film_id": film_id,
            "title": title,
            "year": year,
            "poster_path": poster,
            "starts_at": starts_at,
            "status": status,
            "expected": expected,
            "came": came,
            "rating": round(float(rating), 2) if rating is not None else None,
        }
        for sid, film_id, title, year, poster, starts_at, status, expected, came, rating in rows
    ]


async def current_stage_label(session: AsyncSession) -> str:
    round_ = (
        await session.execute(
            sa.select(Round).where(Round.stage != RoundStage.CLOSED).limit(1)
        )
    ).scalar_one_or_none()
    return round_.stage if round_ else "нет активного цикла"
