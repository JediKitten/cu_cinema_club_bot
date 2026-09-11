"""Жизненный цикл цикла (§2, §3, §5).

Цикл — одна неделя показов. Здесь только переходы, которые инициирует человек;
расписание по времени (срезы, автопилоты, публикация) появится вместе с
планировщиком, но опираться будет на эти же функции.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Film, Hall, Round, ShortlistItem, Slot, User
from app.models.enums import NotificationKind, RoundStage, ShortlistSource
from app.services import notify
from app.services.settings import SettingsService

DAYS_IN_WEEK = 7


class RoundError(ValueError):
    """Нарушение порядка этапов — показываем администратору как есть."""


def deadline_moment(week_start: date, spec: str, tz_name: str) -> datetime:
    """Абсолютный момент дедлайна вида «<день недели> ЧЧ:ММ» (§13).

    Дедлайны относятся к неделе, ПРЕДШЕСТВУЮЩЕЙ неделе показов: шорт-лист
    собирают до её начала, а не во время.
    """
    weekday, clock = spec.split()
    hour, minute = (int(part) for part in clock.split(":"))
    prev_monday = week_start - timedelta(days=DAYS_IN_WEEK)
    return datetime.combine(
        prev_monday + timedelta(days=int(weekday)),
        time(hour, minute),
        tzinfo=ZoneInfo(tz_name),
    )


@dataclass(frozen=True, slots=True)
class ShortlistWindow:
    """Окно, в котором шорт-лист собирают руками (по решению клуба).

    Открывается срезом этапа 1 и закрывается временем автопилота: до среза
    веса ещё набираются и список был бы преждевременным, после автопилота
    список уже уходит в голосование. Границы — те же параметры §13, что
    двигают цикл, чтобы окно и автоматика не разъезжались.
    """

    opens_at: datetime
    closes_at: datetime
    now: datetime

    @property
    def is_open(self) -> bool:
        return self.opens_at <= self.now < self.closes_at


def shortlist_window(
    week_start: date, values: dict, now: datetime | None = None
) -> ShortlistWindow:
    tz = str(values["display_timezone"])
    return ShortlistWindow(
        opens_at=deadline_moment(week_start, str(values["stage1_cut_at"]), tz),
        closes_at=deadline_moment(week_start, str(values["stage1_autopilot_at"]), tz),
        now=now or datetime.now(UTC),
    )


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
    session: AsyncSession,
    round_: Round,
    film_ids: list[int],
    actor_id: int,
    now: datetime | None = None,
) -> list[ShortlistItem]:
    """Заменяет шорт-лист целиком.

    Правка списка после публикации меняла бы условия голосования на ходу,
    поэтому разрешена только до неё — и только внутри окна сборки
    (см. shortlist_window).
    """
    if round_.stage not in (RoundStage.COLLECTING, RoundStage.SHORTLIST_REVIEW):
        raise RoundError("Шорт-лист уже опубликован, править его нельзя")

    values = await SettingsService(session).all()
    window = shortlist_window(round_.week_start, values, now)
    if not window.is_open:
        tz = ZoneInfo(str(values["display_timezone"]))
        when = window.opens_at.astimezone(tz).strftime("%d.%m в %H:%M")
        raise RoundError(
            "Шорт-лист собирают только в окне с "
            f"{window.opens_at.astimezone(tz):%H:%M} до "
            f"{window.closes_at.astimezone(tz):%H:%M}. "
            + ("Оно уже закрылось." if window.now >= window.closes_at else f"Откроется {when}.")
        )

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

    # Об открытии голосования надо сказать вслух. Без этого весь этап 2 —
    # а при включённом автопилоте он и начинается сам — проходил молча: человек
    # узнавал о нём, только если случайно открывал приложение в эти три дня.
    titles = (
        (
            await session.execute(
                sa.select(Film.title_ru)
                .join(ShortlistItem, ShortlistItem.film_id == Film.id)
                .where(ShortlistItem.round_id == round_.id)
                .order_by(ShortlistItem.position)
            )
        )
        .scalars()
        .all()
    )
    audience = (
        (
            await session.execute(
                sa.select(User.id).where(User.is_active, User.tg_id.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    for user_id in audience:
        await notify.queue(
            session,
            user_id,
            NotificationKind.SHORTLIST_PUBLISHED,
            dedup_key=f"shortlist:{round_.id}:{user_id}",
            payload={"films": list(titles)},
        )

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
