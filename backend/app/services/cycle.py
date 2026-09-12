"""Продвижение цикла по дедлайнам (§3, §17).

Одна функция `tick()` смотрит на текущий цикл и делает ровно один шаг, если
его срок наступил. Вызывается часто, поэтому обязана быть идемпотентной:
каждый переход проверяет текущий этап и не повторяется.
"""

import logging
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Round, Screening, Slot
from app.models.enums import RoundStage, ScreeningStatus
from app.services import autopilot
from app.services import rounds as rounds_service
from app.services import schedule as schedule_service
from app.services.rounds import RoundError
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Сколько недель вперёд готовы пропустить, подбирая неделю для нового цикла.
MAX_WEEKS_AHEAD = 4


async def tick(session: AsyncSession) -> list[str]:
    """Один проход. Возвращает список выполненных переходов — для лога."""
    values = await SettingsService(session).all()
    tz = str(values["display_timezone"])
    done: list[str] = []

    # Показы, которые уже прошли, закрываем всегда — даже когда цикла нет
    # вовсе: ручные события ему не принадлежат.
    if await _complete_past(session):
        done.append("прошедшие показы отмечены завершёнными")

    round_ = await rounds_service.active_round(session)

    if round_ is None:
        # Цикла нет — заводим, чтобы люди могли голосовать, когда придёт срок.
        round_ = await rounds_service.open_round(
            session, _first_collectable_week(values, tz), actor_id=None
        )
        done.append(f"открыт цикл на {round_.week_start}")

    def passed(setting: str) -> bool:
        """Наступил ли дедлайн, заданный параметром §13."""
        return autopilot.deadline_passed(round_.week_start, str(values[setting]), tz)

    if round_.stage == RoundStage.COLLECTING and passed("stage1_autopilot_at"):
        if values["autopilot_stage1_enabled"]:
            count = await autopilot.apply_shortlist(session, round_)
            done.append(f"автопилот собрал шорт-лист: {count}")
        else:
            # Тумблер выключен — ждём человека, но подсказку всё равно считаем (§5).
            await autopilot.propose_shortlist(session, round_)

    if round_.stage == RoundStage.SHORTLIST_REVIEW and passed("shortlist_publish_at"):
        try:
            await rounds_service.publish_shortlist(session, round_, actor_id=None)
            done.append("шорт-лист опубликован")
        except RoundError as exc:
            logger.warning("Не удалось опубликовать шорт-лист: %s", exc)

    if round_.stage == RoundStage.SLOT_VOTING and passed("stage2_autopilot_at"):
        if values["autopilot_stage2_enabled"]:
            placed = await autopilot.apply_schedule(session, round_, actor_id=None)
            done.append(f"автопилот расставил показы: {placed}")
        else:
            await autopilot.propose_schedule(session, round_)

    if round_.stage == RoundStage.SCHEDULE_REVIEW and passed("schedule_publish_at"):
        try:
            await schedule_service.publish_schedule(session, round_, actor_id=None)
            done.append("расписание опубликовано")
        except schedule_service.ScheduleError as exc:
            logger.warning("Не удалось опубликовать расписание: %s", exc)

    if round_.stage == RoundStage.PUBLISHED and _week_started(round_.week_start):
        round_.stage = RoundStage.RUNNING
        await session.commit()
        done.append("неделя показов началась")

    if round_.stage == RoundStage.RUNNING and await _week_finished(session, round_):
        await _close(session, round_)
        done.append("цикл закрыт")

    if done:
        logger.info("Цикл %s: %s", round_.week_start, "; ".join(done))
    return done


def _first_collectable_week(
    values: dict, tz: str, now: datetime | None = None
) -> date:
    """Ближайшая неделя показов, по которой ещё можно успеть собрать интерес.

    Дедлайны отсчитываются от недели, ПРЕДШЕСТВУЮЩЕЙ показам. В обычном ритме
    цикл закрывается в понедельник, и у следующей недели все сроки впереди.
    Но если цикла нет вовсе — бота запустили впервые или он долго лежал, —
    ближайший понедельник может оказаться таким, что его дедлайны уже в
    прошлом. Тогда один проход `tick` собрал бы шорт-лист, опубликовал его,
    расставил показы и объявил расписание подряд, не дав людям ни минуты
    ни на отметки, ни на голосование. Пропускаем такие недели.
    """
    week = rounds_service.next_week_start(now.date() if now else None)
    for _ in range(MAX_WEEKS_AHEAD):
        if not autopilot.deadline_passed(week, str(values["stage1_cut_at"]), tz, now):
            return week
        week += timedelta(days=rounds_service.DAYS_IN_WEEK)
    return week


async def _complete_past(session: AsyncSession) -> int:
    """Отмечает завершёнными показы, которые уже кончились.

    Раньше это делало только закрытие цикла и только для его показов. У ручного
    события цикла нет, поэтому оно оставалось «назначенным» навсегда — и не
    попадало ни в «Что уже смотрели», ни в статистику, хотя прошло неделю назад.

    Момент — конец слота: длительность уже учитывает фильм целиком, а ждать
    дольше незачем.
    """
    ended = Slot.starts_at + sa.cast(
        sa.func.concat(Slot.duration_min, " minutes"), postgresql.INTERVAL
    )
    result = await session.execute(
        sa.update(Screening)
        .where(
            Screening.status == ScreeningStatus.SCHEDULED,
            Screening.slot_id.in_(sa.select(Slot.id).where(ended < sa.func.now())),
        )
        .values(status=ScreeningStatus.COMPLETED)
    )
    if result.rowcount:
        await session.commit()
        logger.info("Завершено показов: %d", result.rowcount)
    return result.rowcount


def _week_started(week_start: date, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return now.date() >= week_start


async def _week_finished(session: AsyncSession, round_: Round) -> bool:
    """Неделя закончилась, когда прошёл последний слот цикла."""
    last = await session.scalar(
        sa.select(sa.func.max(Slot.starts_at)).where(Slot.round_id == round_.id)
    )
    if last is None:
        return True
    # Ждём конца самого позднего вечера, а не его начала: показ ещё идёт.
    return datetime.now(UTC) > last + timedelta(hours=6)


async def _close(session: AsyncSession, round_: Round) -> None:
    """Закрывает цикл и помечает проведённые показы завершёнными."""
    await session.execute(
        sa.update(Screening)
        .where(Screening.round_id == round_.id, Screening.status == ScreeningStatus.SCHEDULED)
        .values(status=ScreeningStatus.COMPLETED)
    )
    round_.stage = RoundStage.CLOSED
    await session.commit()
