"""Этап 4 — присутствие и обратная связь (§8).

Код присутствия устроен в духе TOTP: он не хранится, а выводится из секрета
показа и номера временного интервала. Поэтому «украсть» его из базы нельзя,
а старый код перестаёт работать сам собой.

Контур защиты (§8) — не в стойкости кода, а в трёх ограничениях сразу:
код живёт минуту, принимается только в окне после начала сеанса и только от
тех, кто подтверждал приход.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendance, Confirmation, Feedback, Interest, Screening, Slot, Watch
from app.models.enums import (
    AttendanceMethod,
    ConfirmationState,
    DiscussionSkip,
    RevokeReason,
    ScreeningStatus,
)
from app.services import ratings

CODE_LENGTH = 6


class AttendanceError(ValueError):
    """Причину показываем человеку как есть."""


@dataclass(frozen=True, slots=True)
class CodeInfo:
    code: str
    # Сколько секунд этот код ещё действителен — экран показывает обратный отсчёт.
    valid_for: int
    rotates_every: int


def _derive(secret: str, counter: int) -> str:
    digest = hmac.new(secret.encode(), str(counter).encode(), hashlib.sha256).digest()
    number = int.from_bytes(digest[:4], "big") % (10**CODE_LENGTH)
    return f"{number:0{CODE_LENGTH}d}"


async def ensure_secret(session: AsyncSession, screening: Screening) -> str:
    if not screening.attendance_secret:
        screening.attendance_secret = secrets.token_hex(16)
        await session.commit()
    return screening.attendance_secret


async def current_code(
    session: AsyncSession, screening: Screening, rotation_seconds: int, at: datetime | None = None
) -> CodeInfo:
    secret = await ensure_secret(session, screening)
    now = at or datetime.now(UTC)
    counter = int(now.timestamp()) // rotation_seconds
    used = int(now.timestamp()) % rotation_seconds
    return CodeInfo(
        code=_derive(secret, counter),
        valid_for=rotation_seconds - used,
        rotates_every=rotation_seconds,
    )


def _accepts(secret: str, code: str, rotation_seconds: int, now: datetime) -> bool:
    """Принимаем текущий код и предыдущий.

    Без предыдущего человек, начавший вводить код за секунду до смены, получал
    бы отказ — и не понимал почему.
    """
    counter = int(now.timestamp()) // rotation_seconds
    return any(
        hmac.compare_digest(_derive(secret, counter - shift), code) for shift in (0, 1)
    )


async def window_is_open(
    session: AsyncSession, screening: Screening, window_minutes: int, now: datetime
) -> bool:
    slot = await session.get(Slot, screening.slot_id)
    return slot.starts_at <= now <= slot.starts_at + timedelta(minutes=window_minutes)


async def mark_by_code(
    session: AsyncSession,
    screening_id: int,
    user_id: int,
    code: str,
    rotation_seconds: int,
    window_minutes: int,
    now: datetime | None = None,
) -> Attendance:
    """Отметка присутствия по коду с экрана."""
    now = now or datetime.now(UTC)
    screening = await session.get(Screening, screening_id)
    if screening is None or screening.status == ScreeningStatus.CANCELLED:
        raise AttendanceError("Показ не найден")

    if not await window_is_open(session, screening, window_minutes, now):
        raise AttendanceError("Отметиться можно только в первые минуты сеанса")

    secret = await ensure_secret(session, screening)
    if not _accepts(secret, code.strip(), rotation_seconds, now):
        raise AttendanceError("Код неверный или уже сменился")

    confirmed = await session.scalar(
        sa.select(Confirmation.id).where(
            Confirmation.screening_id == screening_id,
            Confirmation.user_id == user_id,
            Confirmation.state == ConfirmationState.CONFIRMED,
        )
    )
    if confirmed is None:
        # Код легко переслать, поэтому подтверждение на этапе 3 — обязательное
        # условие (§8). Незаписавшегося отмечает модератор вручную.
        raise AttendanceError("Вы не подтверждали приход — попросите отметить вас вручную")

    return await _record(session, screening, user_id, AttendanceMethod.CODE, marked_by=user_id)


async def mark_manually(
    session: AsyncSession, screening_id: int, user_id: int, moderator_id: int
) -> Attendance:
    """Ручная отметка модератором (§8): подтверждение при этом не требуется."""
    screening = await session.get(Screening, screening_id)
    if screening is None or screening.status == ScreeningStatus.CANCELLED:
        raise AttendanceError("Показ не найден")
    return await _record(
        session, screening, user_id, AttendanceMethod.MANUAL, marked_by=moderator_id
    )


async def _record(
    session: AsyncSession,
    screening: Screening,
    user_id: int,
    method: AttendanceMethod,
    marked_by: int,
) -> Attendance:
    existing = (
        await session.execute(
            sa.select(Attendance).where(
                Attendance.screening_id == screening.id, Attendance.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    attendance = Attendance(
        screening_id=screening.id, user_id=user_id, method=method, marked_by=marked_by
    )
    session.add(attendance)

    # Пришёл — значит посмотрел. Отметку интереса при этом снимаем: фильм
    # переходит в «Просмотренные» (§8). У события без фильма (встреча клуба,
    # показ «ждите анонса») смотреть нечего — отмечаем только приход.
    if screening.film_id is not None:
        await session.execute(
            sa.update(Interest)
            .where(
                Interest.user_id == user_id,
                Interest.film_id == screening.film_id,
                Interest.revoked_at.is_(None),
            )
            .values(revoked_at=sa.func.now(), revoke_reason=RevokeReason.WATCHED)
        )

        already_watched = await session.scalar(
            sa.select(Watch.id).where(Watch.user_id == user_id, Watch.film_id == screening.film_id)
        )
        if already_watched is None:
            session.add(
                Watch(
                    user_id=user_id,
                    film_id=screening.film_id,
                    source="attendance",
                    screening_id=screening.id,
                )
            )

    await session.commit()
    return attendance


async def attendees(session: AsyncSession, screening_id: int) -> list[Attendance]:
    """Живой список отметившихся — его видит модератор в зале (§8)."""
    rows = await session.execute(
        sa.select(Attendance)
        .where(Attendance.screening_id == screening_id)
        .order_by(Attendance.marked_at)
    )
    return list(rows.scalars())


async def save_feedback(
    session: AsyncSession,
    screening_id: int,
    user_id: int,
    film_rating: int | None,
    review_text: str | None,
    visit_rating: int | None = None,
    discussion_rating: int | None = None,
    discussion_skip: str | None = None,
) -> Feedback:
    """Опрос после показа (§8, CSAT по просьбе клуба).

    Обязательна только отметка присутствия, сама форма — нет: заполнять её
    из-под палки значило бы собирать вежливые пятёрки вместо правды, а клуб
    отчитывается этими цифрами перед вузом.

    Оценка фильма отсюда — та же, что в каталоге: рейтинг у фильма один,
    откуда бы оценка ни пришла. Впечатление от вечера и обсуждение живут
    отдельно и в рейтинг фильма не входят — плохая проекция не должна
    топить хорошее кино.
    """
    screening = await session.get(Screening, screening_id)
    if screening is None:
        raise AttendanceError("Показ не найден")

    came = await session.scalar(
        sa.select(Attendance.id).where(
            Attendance.screening_id == screening_id, Attendance.user_id == user_id
        )
    )
    if came is None:
        raise AttendanceError("Оценить можно только тот показ, на котором были")

    for value in (film_rating, visit_rating, discussion_rating):
        if value is not None and not 1 <= value <= 10:
            raise AttendanceError("Оценка — от 1 до 10")
    if discussion_rating is not None and discussion_skip is not None:
        raise AttendanceError("У обсуждения либо оценка, либо причина её отсутствия")
    if discussion_skip is not None and discussion_skip not in set(DiscussionSkip):
        raise AttendanceError("Непонятный ответ про обсуждение")

    existing = (
        await session.execute(
            sa.select(Feedback).where(
                Feedback.screening_id == screening_id, Feedback.user_id == user_id
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = Feedback(
            screening_id=screening_id, user_id=user_id, film_id=screening.film_id
        )
        session.add(existing)

    existing.film_rating = film_rating
    existing.visit_rating = visit_rating
    existing.discussion_rating = discussion_rating
    existing.discussion_skip = DiscussionSkip(discussion_skip) if discussion_skip else None
    existing.review_text = (review_text or "").strip() or None

    # Рейтинг у фильма один, откуда бы оценка ни пришла: десятибалльная шкала
    # формы — те же полубаллы, что и пять звёзд в каталоге.
    if screening.film_id is not None and film_rating is not None:
        await ratings.set_rating(
            session, user_id, screening.film_id, film_rating / 2, source="screening"
        )

    await session.commit()
    return existing
