"""Автопилоты этапов 1 и 2 (§5, §6).

Автопилот считает своё решение ВСЕГДА, даже когда администратор работает
вручную, и показывается рядом как подсказка. Применяется он только если к
дедлайну человек ничего не подтвердил.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

import sqlalchemy as sa
from scipy.optimize import linear_sum_assignment
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AutopilotProposal, Round, ShortlistItem, Slot
from app.models.enums import RoundStage, ShortlistSource
from app.services import rounds as rounds_service
from app.services import schedule as schedule_service
from app.services import voting
from app.services.ranking import rank_by_coverage
from app.services.settings import SettingsService
from app.services.weights import WeightParams

logger = logging.getLogger(__name__)

# Понедельник ставим последним: между публикацией расписания и понедельничным
# показом меньше суток (§3).
MONDAY = 0


@dataclass(slots=True)
class Assignment:
    film_id: int
    slot_id: int
    expected: int


async def propose_shortlist(
    session: AsyncSession, round_: Round, *, deciding: bool = False
) -> list[int]:
    """Решение автопилота для этапа 1: рейтинг по покрытию с отсевом по порогу.

    `deciding` — автопилот действительно принимает решение, а не считает
    подсказку. Только тогда уместен флаг низкой активности: на свежем цикле
    отметок ещё физически нет, и флаг был бы ложной тревогой.
    """
    values = await SettingsService(session).all()
    ranked = await rank_by_coverage(
        session,
        WeightParams.from_settings(values),
        long_wait_days=int(values["long_wait_days"]),
        size=int(values["shortlist_size"]),
        min_weight=float(values["min_weight_threshold"]),
    )
    film_ids = [row.film_id for row in ranked]

    await _save_proposal(
        session,
        round_,
        stage=1,
        payload={"film_ids": film_ids, "titles": [row.title_ru for row in ranked]},
    )
    # Прошедших порог меньше нужного — цикл идёт с флагом низкой активности (§5).
    if deciding:
        round_.low_activity = len(film_ids) < int(values["shortlist_size"])
    await session.commit()
    return film_ids


async def propose_schedule(session: AsyncSession, round_: Round) -> list[Assignment]:
    """Решение автопилота для этапа 2 — задача о назначениях (§6).

    Матрица стоимостей — ожидаемая явка; scipy решает на максимум. Слоты, где
    явка ниже кворума, не назначаются вовсе: показ ради двух человек не нужен.
    """
    values = await SettingsService(session).all()
    minimum = int(values["min_attendance"])
    per_week = int(values["screenings_per_week"])

    matrix = await voting.build_matrix(session, round_)
    films = matrix.film_ids
    slots = await voting.open_slots(session, round_)
    if not films or not slots:
        await _save_proposal(session, round_, stage=2, payload={"assignments": []})
        await session.commit()
        return []

    # Ранг фильма в шорт-листе — тай-брейк: при равной явке приоритет тому,
    # кто дольше ждёт показа (§6).
    positions = dict(
        (
            await session.execute(
                sa.select(ShortlistItem.film_id, ShortlistItem.position).where(
                    ShortlistItem.round_id == round_.id
                )
            )
        ).all()
    )

    cost = []
    for film_id in films:
        row = []
        for slot in slots:
            expected = matrix.cell(film_id, slot.id)
            # Крошечная добавка за место в шорт-листе: на сам выбор она влияет
            # только когда явка совпала.
            tiebreak = (len(films) - positions.get(film_id, 0)) * 1e-4
            row.append(-(expected + tiebreak) if expected >= minimum else 0.0)
        cost.append(row)

    rows, cols = linear_sum_assignment(cost)

    assignments = []
    for r, c in zip(rows, cols, strict=False):
        film_id, slot = films[r], slots[c]
        expected = matrix.cell(film_id, slot.id)
        if expected < minimum:
            # Ниже кворума показ не назначается вовсе (§6).
            continue
        assignments.append(Assignment(film_id=film_id, slot_id=slot.id, expected=expected))

    # Сколько фильмов клуб смотрит за неделю — параметр §13. Задача
    # о назначениях заполнила бы все свободные вечера; оставляем столько
    # показов с лучшей ожидаемой явкой, сколько клуб готов провести.
    assignments.sort(key=lambda item: item.expected, reverse=True)
    assignments = assignments[:per_week]

    assignments = _monday_last(assignments, slots)
    await _save_proposal(
        session,
        round_,
        stage=2,
        payload={
            "assignments": [
                {"film_id": a.film_id, "slot_id": a.slot_id, "expected": a.expected}
                for a in assignments
            ]
        },
    )
    await session.commit()
    return assignments


def _monday_last(assignments: list[Assignment], slots: list[Slot]) -> list[Assignment]:
    """Понедельник используем в последнюю очередь (§3).

    Между публикацией расписания и понедельничным показом меньше суток —
    люди просто не успеют увидеть приглашение.
    """
    by_id = {slot.id: slot for slot in slots}
    return sorted(
        assignments,
        key=lambda a: (by_id[a.slot_id].starts_at.weekday() == MONDAY, by_id[a.slot_id].starts_at),
    )


async def _save_proposal(
    session: AsyncSession, round_: Round, stage: int, payload: dict
) -> None:
    payload = {**payload, "computed_at": datetime.now(UTC).isoformat(timespec="seconds")}
    existing = (
        await session.execute(
            sa.select(AutopilotProposal).where(
                AutopilotProposal.round_id == round_.id, AutopilotProposal.stage == stage
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(AutopilotProposal(round_id=round_.id, stage=stage, payload=payload))
    else:
        existing.payload = payload


async def apply_shortlist(session: AsyncSession, round_: Round) -> int:
    """Ставит предложенный шорт-лист, если человек не успел (§5)."""
    if round_.stage != RoundStage.COLLECTING:
        return 0

    film_ids = await propose_shortlist(session, round_, deciding=True)
    if not film_ids:
        round_.skipped_reason = "Нет фильмов выше порога веса"
        await session.commit()
        return 0

    await session.execute(sa.delete(ShortlistItem).where(ShortlistItem.round_id == round_.id))
    session.add_all(
        ShortlistItem(
            round_id=round_.id,
            film_id=film_id,
            source=ShortlistSource.AUTO_COVERAGE,
            position=position,
        )
        for position, film_id in enumerate(film_ids)
    )
    round_.stage = RoundStage.SHORTLIST_REVIEW
    await session.commit()
    return len(film_ids)


async def apply_schedule(session: AsyncSession, round_: Round, actor_id: int | None) -> int:
    """Расставляет показы, если администратор не успел (§6)."""
    if round_.stage != RoundStage.SLOT_VOTING:
        return 0

    assignments = await propose_schedule(session, round_)
    placed = 0
    for item in assignments:
        try:
            await schedule_service.assign(session, round_, item.film_id, item.slot_id, actor_id)
            placed += 1
        except schedule_service.ScheduleError as exc:
            # Занятый слот или уже стоящий фильм — не повод падать целиком.
            logger.warning("Автопилот пропустил назначение: %s", exc)
    return placed


def deadline_passed(
    week_start: date, spec: str, tz_name: str, now: datetime | None = None
) -> bool:
    """Наступил ли дедлайн вида «<день недели> ЧЧ:ММ» (§13).

    Дедлайны относятся к неделе, ПРЕДШЕСТВУЮЩЕЙ неделе показов: шорт-лист
    собирают до её начала, а не во время.
    """
    # Сам момент считает rounds: тем же расчётом живёт окно сборки шорт-листа,
    # и разъехаться они не должны.
    return (now or datetime.now(UTC)) >= rounds_service.deadline_moment(
        week_start, spec, tz_name
    )
