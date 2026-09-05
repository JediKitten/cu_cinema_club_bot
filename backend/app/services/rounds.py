"""Жизненный цикл цикла (§2, §3, §5).

Цикл — одна неделя показов. Здесь только переходы, которые инициирует человек;
расписание по времени (срезы, автопилоты, публикация) появится вместе с
планировщиком, но опираться будет на эти же функции.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, AutopilotProposal, Hall, Round, ShortlistItem, Slot
from app.models.enums import RoundStage, ShortlistSource
from app.services.ranking import rank_by_coverage
from app.services.settings import SettingsService
from app.services.weights import WeightParams

DAYS_IN_WEEK = 7


class RoundError(ValueError):
    """Нарушение порядка этапов — показываем администратору как есть."""


def week_start_for(moment: date) -> date:
    """Понедельник недели, в которую попадает дата."""
    return moment - timedelta(days=moment.weekday())


def next_week_start(today: date | None = None) -> date:
    """Ближайший будущий понедельник.

    Цикл всегда готовится к следующей неделе: на текущей показы уже назначены
    или идут, и менять шорт-лист задним числом бессмысленно.
    """
    today = today or date.today()
    return week_start_for(today) + timedelta(days=DAYS_IN_WEEK)


async def ensure_hall(session: AsyncSession) -> Hall:
    """Пока зал один (§10), но модель уже знает про несколько.

    Вместимость берём из настроек: она же ограничивает подтверждения на этапе 3.
    """
    hall = (await session.execute(sa.select(Hall).where(Hall.active))).scalars().first()
    capacity = int(await SettingsService(session).get("hall_capacity"))
    if hall is None:
        hall = Hall(name="Основной зал", capacity=capacity)
        session.add(hall)
        await session.flush()
    elif hall.capacity != capacity:
        # Настройку могли поменять между циклами — зал должен следовать за ней.
        hall.capacity = capacity
    return hall


async def _create_slots(session: AsyncSession, round_: Round, hall: Hall) -> list[Slot]:
    """Семь вечеров недели: по одному слоту на день (§10).

    Время хранится в UTC, а задаётся в локальной зоне вуза — поэтому переводим
    явно, а не прибавляем фиксированное смещение: иначе переход на летнее время
    сдвинул бы все показы.
    """
    values = await SettingsService(session).all()
    tz = ZoneInfo(str(values["display_timezone"]))
    hour, minute = (int(part) for part in str(values["screening_start_time"]).split(":"))
    duration = int(values["screening_duration_min"])

    slots = []
    for offset in range(DAYS_IN_WEEK):
        day = round_.week_start + timedelta(days=offset)
        local = datetime.combine(day, time(hour, minute), tzinfo=tz)
        slot = Slot(
            round_id=round_.id,
            hall_id=hall.id,
            starts_at=local.astimezone(ZoneInfo("UTC")),
            duration_min=duration,
        )
        session.add(slot)
        slots.append(slot)
    await session.flush()
    return slots


async def open_round(
    session: AsyncSession, week_start: date | None = None, actor_id: int | None = None
) -> Round:
    """Заводит цикл на неделю и слоты под него. Идемпотентна по неделе."""
    week_start = week_start or next_week_start()
    if week_start.weekday() != 0:
        raise RoundError("Неделя цикла должна начинаться с понедельника")

    existing = (
        await session.execute(sa.select(Round).where(Round.week_start == week_start))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    round_ = Round(week_start=week_start, stage=RoundStage.COLLECTING)
    session.add(round_)
    await session.flush()

    await _create_slots(session, round_, await ensure_hall(session))
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="round",
            entity_id=round_.id,
            action="open",
            payload={"week_start": week_start.isoformat()},
        )
    )
    await session.commit()
    return round_


async def active_round(session: AsyncSession) -> Round | None:
    """Цикл, который сейчас в работе. Закрытые не в счёт."""
    return (
        await session.execute(
            sa.select(Round)
            .where(Round.stage != RoundStage.CLOSED)
            .order_by(Round.week_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def set_shortlist(
    session: AsyncSession, round_: Round, film_ids: list[int], actor_id: int
) -> list[ShortlistItem]:
    """Заменяет шорт-лист целиком.

    Правка списка после публикации меняла бы условия голосования на ходу,
    поэтому разрешена только до неё.
    """
    if round_.stage not in (RoundStage.COLLECTING, RoundStage.SHORTLIST_REVIEW):
        raise RoundError("Шорт-лист уже опубликован, править его нельзя")
    if not film_ids:
        raise RoundError("Шорт-лист не может быть пустым")
    if len(set(film_ids)) != len(film_ids):
        raise RoundError("В шорт-листе повторяются фильмы")

    await session.execute(sa.delete(ShortlistItem).where(ShortlistItem.round_id == round_.id))

    items = [
        ShortlistItem(
            round_id=round_.id,
            film_id=film_id,
            source=ShortlistSource.ADMIN,
            position=position,
        )
        for position, film_id in enumerate(film_ids)
    ]
    session.add_all(items)
    round_.stage = RoundStage.SHORTLIST_REVIEW
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="round",
            entity_id=round_.id,
            action="set_shortlist",
            payload={"film_ids": film_ids},
        )
    )
    await session.commit()
    return items


async def publish_shortlist(session: AsyncSession, round_: Round, actor_id: int) -> Round:
    """Открывает этап 2: список зафиксирован, идёт голосование по фильмам и вечерам."""
    if round_.stage == RoundStage.COLLECTING:
        raise RoundError("Сначала соберите шорт-лист")
    if round_.stage != RoundStage.SHORTLIST_REVIEW:
        raise RoundError("Шорт-лист уже опубликован")

    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(ShortlistItem)
            .where(ShortlistItem.round_id == round_.id)
        )
    ).scalar_one()
    if not count:
        raise RoundError("Шорт-лист пуст")

    # Если все вечера заблокированы, голосовать не за что (§3).
    free_slots = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(Slot)
            .where(Slot.round_id == round_.id, Slot.blocked.is_(False))
        )
    ).scalar_one()
    if not free_slots:
        raise RoundError("Все вечера недели заблокированы — показов не будет")

    round_.stage = RoundStage.SLOT_VOTING
    round_.shortlist_locked_at = datetime.now(ZoneInfo("UTC"))
    session.add(
        AuditLog(actor_id=actor_id, entity="round", entity_id=round_.id, action="publish_shortlist")
    )
    await session.commit()
    return round_


async def set_slot_blocked(
    session: AsyncSession, slot_id: int, blocked: bool, reason: str | None, actor_id: int
) -> Slot:
    slot = await session.get(Slot, slot_id)
    if slot is None:
        raise RoundError("Слот не найден")
    slot.blocked = blocked
    slot.blocked_reason = reason if blocked else None
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="slot",
            entity_id=slot_id,
            action="block" if blocked else "unblock",
            comment=reason,
        )
    )
    await session.commit()
    return slot


async def autopilot_shortlist(
    session: AsyncSession, round_: Round, *, deciding: bool = False
) -> list[int]:
    """Решение автопилота для этапа 1.

    Считается всегда, даже когда админ работает вручную, и показывается рядом
    как подсказка (§5). Сохраняем, чтобы потом сравнить с тем, что выбрал человек.

    `deciding` — автопилот действительно принимает решение (сработал в срез),
    а не считает подсказку. Только тогда имеет смысл флаг низкой активности:
    на свежем цикле отметок ещё физически нет, и флаг был бы ложной тревогой.
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

    payload = {
        "film_ids": film_ids,
        "titles": [row.title_ru for row in ranked],
        "computed_at": datetime.now(ZoneInfo("UTC")).isoformat(),
    }
    existing = (
        await session.execute(
            sa.select(AutopilotProposal).where(
                AutopilotProposal.round_id == round_.id, AutopilotProposal.stage == 1
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(AutopilotProposal(round_id=round_.id, stage=1, payload=payload))
    else:
        existing.payload = payload

    # Прошедших порог меньше, чем нужно, — цикл идёт с флагом низкой активности (§5).
    if deciding:
        round_.low_activity = len(film_ids) < int(values["shortlist_size"])
    await session.commit()
    return film_ids
