"""Этап 3 — расписание и подтверждения (§7).

Здесь два разных дела. Первое: администратор расставляет показы по слотам,
опираясь на матрицу этапа 2, и публикует расписание. Второе: зрители
подтверждают приход, а вместимость зала превращает лишние подтверждения
в лист ожидания.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Confirmation,
    Film,
    FilmVote,
    Hall,
    Round,
    Screening,
    Slot,
)
from app.models.enums import (
    ConfirmationState,
    NotificationKind,
    RoundStage,
    ScreeningStatus,
)
from app.services import notify
from app.services.voting import build_matrix


class ScheduleError(ValueError):
    """Причину показываем администратору как есть."""


# --- Расстановка показов ---------------------------------------------------


async def assign(
    session: AsyncSession, round_: Round, film_id: int, slot_id: int, actor_id: int
) -> Screening:
    """Ставит показ в слот. Ограничения §6 держит база частичными индексами,
    но проверяем и здесь — чтобы отдать человеку понятную причину, а не 500."""
    if round_.stage not in (RoundStage.SLOT_VOTING, RoundStage.SCHEDULE_REVIEW):
        raise ScheduleError("Расписание уже опубликовано — правьте через перенос показа")

    slot = await session.get(Slot, slot_id)
    if slot is None or slot.round_id != round_.id:
        raise ScheduleError("Слот не из этого цикла")
    if slot.blocked:
        raise ScheduleError("Этот вечер закрыт")

    taken = await session.scalar(
        sa.select(Screening.id).where(
            Screening.slot_id == slot_id, Screening.status != ScreeningStatus.CANCELLED
        )
    )
    if taken:
        raise ScheduleError("На этот вечер уже назначен показ")

    same_film = await session.scalar(
        sa.select(Screening.id).where(
            Screening.round_id == round_.id,
            Screening.film_id == film_id,
            Screening.status != ScreeningStatus.CANCELLED,
        )
    )
    if same_film:
        raise ScheduleError("Этот фильм уже стоит в расписании недели")

    matrix = await build_matrix(session, round_)
    screening = Screening(
        round_id=round_.id,
        film_id=film_id,
        slot_id=slot_id,
        # Ожидаемая явка — та самая ячейка матрицы. Сохраняем снимком: позже
        # по ней сверяют, насколько прогноз сошёлся с фактом (§14).
        expected_attendance=matrix.cell(film_id, slot_id),
        # Неделю объявили англоязычной до того, как выбрали фильм: показ
        # наследует пометку, иначе о ней пришлось бы вспоминать вручную.
        in_english=round_.in_english,
        decided_by=actor_id,
        decided_at=datetime.now(UTC),
    )
    session.add(screening)
    round_.stage = RoundStage.SCHEDULE_REVIEW
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="screening",
            action="assign",
            payload={"film_id": film_id, "slot_id": slot_id},
        )
    )
    await session.commit()
    return screening


async def unassign(
    session: AsyncSession, round_: Round, screening_id: int, actor_id: int
) -> None:
    """Снимает ещё не опубликованный показ.

    После публикации показ не удаляют, а отменяют с комментарием (§7): люди
    уже могли подтвердить приход, и молча стирать сеанс нельзя.
    """
    if round_.stage != RoundStage.SCHEDULE_REVIEW:
        raise ScheduleError("Снять показ можно только до публикации")

    screening = await session.get(Screening, screening_id)
    if screening is None or screening.round_id != round_.id:
        raise ScheduleError("Показ не найден")

    await session.delete(screening)
    session.add(
        AuditLog(
            actor_id=actor_id, entity="screening", entity_id=screening_id, action="unassign"
        )
    )
    await session.commit()


async def publish_schedule(session: AsyncSession, round_: Round, actor_id: int) -> Round:
    """Публикация расписания открывает этап 3 и рассылает приглашения (§7)."""
    if round_.stage == RoundStage.SLOT_VOTING:
        raise ScheduleError("Сначала расставьте показы")
    if round_.stage != RoundStage.SCHEDULE_REVIEW:
        raise ScheduleError("Расписание уже опубликовано")

    screenings = (
        (
            await session.execute(
                sa.select(Screening).where(
                    Screening.round_id == round_.id,
                    Screening.status == ScreeningStatus.SCHEDULED,
                )
            )
        )
        .scalars()
        .all()
    )
    if not screenings:
        raise ScheduleError("В расписании нет ни одного показа")

    round_.stage = RoundStage.PUBLISHED
    round_.schedule_locked_at = datetime.now(UTC)
    round_.published_at = datetime.now(UTC)

    # Уведомляем только тех, кто голосовал за назначенный фильм (§7).
    for screening in screenings:
        voters = (
            (
                await session.execute(
                    sa.select(FilmVote.user_id).where(
                        FilmVote.round_id == round_.id, FilmVote.film_id == screening.film_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in voters:
            # Ключ идемпотентности: повторная публикация не должна рассылать
            # людям второе приглашение на тот же сеанс.
            await notify.queue(
                session,
                user_id,
                NotificationKind.SCHEDULE_PUBLISHED,
                dedup_key=f"published:{screening.id}:{user_id}",
                payload={"screening_id": screening.id, "film_id": screening.film_id},
            )

    session.add(
        AuditLog(
            actor_id=actor_id, entity="round", entity_id=round_.id, action="publish_schedule"
        )
    )
    await session.commit()
    return round_


# --- Подтверждения ---------------------------------------------------------


@dataclass(slots=True)
class ConfirmResult:
    state: ConfirmationState
    place_in_queue: int | None
    capacity: int
    confirmed: int


async def _capacity(session: AsyncSession, screening: Screening) -> int:
    slot = await session.get(Slot, screening.slot_id)
    hall = await session.get(Hall, slot.hall_id)
    return hall.capacity


async def _lock_screening(session: AsyncSession, screening_id: int) -> Screening | None:
    """Берёт показ под блокировку строки до конца транзакции.

    Места в зале считаются чтением, а занимаются записью, и между этими двумя
    шагами успевает вклиниться чужой запрос: два одновременных «Приду» на
    последнее место оба видели свободное. Блокировка строки показа сериализует
    только его — на соседние сеансы и на остальное приложение она не влияет.
    """
    return (
        await session.execute(
            sa.select(Screening).where(Screening.id == screening_id).with_for_update()
        )
    ).scalar_one_or_none()


async def _confirmed_count(session: AsyncSession, screening_id: int) -> int:
    return (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Confirmation)
            .where(
                Confirmation.screening_id == screening_id,
                Confirmation.state == ConfirmationState.CONFIRMED,
            )
        )
        or 0
    )


async def confirm(
    session: AsyncSession, screening_id: int, user_id: int
) -> ConfirmResult:
    """«Приду». Ограничений на число сеансов у одного человека нет (§7)."""
    screening = await _lock_screening(session, screening_id)
    if screening is None:
        raise ScheduleError("Показ не найден")
    if screening.status != ScreeningStatus.SCHEDULED:
        raise ScheduleError("Показ отменён")

    # Ручное событие живёт вне цикла: оно уже объявлено, и этап цикла к нему
    # отношения не имеет. Проверять стадию есть смысл только у показов цикла.
    if screening.round_id is not None:
        round_ = await session.get(Round, screening.round_id)
        if round_ is None or round_.stage not in (RoundStage.PUBLISHED, RoundStage.RUNNING):
            raise ScheduleError("Расписание ещё не опубликовано")

    capacity = await _capacity(session, screening)
    existing = (
        await session.execute(
            sa.select(Confirmation).where(
                Confirmation.screening_id == screening_id, Confirmation.user_id == user_id
            )
        )
    ).scalar_one_or_none()

    if existing is not None and existing.state == ConfirmationState.CONFIRMED:
        return await _result(session, screening_id, existing, capacity)

    # Стоящего в очереди повторное нажатие никуда не двигает: место освобождает
    # только promote_from_waitlist, и по порядку. Иначе очередь доставалась бы
    # тому, кто чаще открывает приложение, а не тому, кто встал раньше.
    if existing is not None and existing.state == ConfirmationState.WAITLIST:
        return await _result(session, screening_id, existing, capacity)

    # Место есть — подтверждаем, иначе в лист ожидания в порядке подтверждения.
    taken = await _confirmed_count(session, screening_id)
    state = (
        ConfirmationState.CONFIRMED if taken < capacity else ConfirmationState.WAITLIST
    )

    if existing is None:
        existing = Confirmation(screening_id=screening_id, user_id=user_id, state=state)
        session.add(existing)
    else:
        existing.state = state
        existing.cancelled_at = None
        existing.was_late_cancel = False
        # Порядок очереди считается по created_at. Вернувшийся после отмены
        # встаёт в её конец: место, которое он сам освободил, уже чужое.
        existing.created_at = datetime.now(UTC)

    # У показа может быть своя регистрация — вуз ведёт учёт отдельно от клуба.
    # Ссылку отдаём сразу, пока человек помнит, на что записался; dedup_key
    # держит её одной на пару «человек + показ», сколько бы раз он ни
    # передумывал.
    if screening.registration_url:
        await notify.queue(
            session,
            user_id,
            NotificationKind.REGISTRATION_LINK,
            dedup_key=f"registration:{screening_id}:{user_id}",
            payload={
                "screening_id": screening_id,
                "url": screening.registration_url,
                "waitlist": state == ConfirmationState.WAITLIST,
            },
        )

    await session.commit()
    return await _result(session, screening_id, existing, capacity)


async def _result(
    session: AsyncSession, screening_id: int, confirmation: Confirmation, capacity: int
) -> ConfirmResult:
    place = None
    if confirmation.state == ConfirmationState.WAITLIST:
        earlier = (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Confirmation)
                .where(
                    Confirmation.screening_id == screening_id,
                    Confirmation.state == ConfirmationState.WAITLIST,
                    Confirmation.created_at < confirmation.created_at,
                )
            )
            or 0
        )
        place = earlier + 1
    return ConfirmResult(
        state=confirmation.state,
        place_in_queue=place,
        capacity=capacity,
        confirmed=await _confirmed_count(session, screening_id),
    )


async def cancel(
    session: AsyncSession, screening_id: int, user_id: int, late_cancel_hours: int
) -> ConfirmResult:
    """«Не смогу». Санкций нет, но поздняя отмена попадает в статистику (§7)."""
    screening = await _lock_screening(session, screening_id)
    if screening is None:
        raise ScheduleError("Показ не найден")

    confirmation = (
        await session.execute(
            sa.select(Confirmation).where(
                Confirmation.screening_id == screening_id, Confirmation.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if confirmation is None or confirmation.state == ConfirmationState.CANCELLED:
        raise ScheduleError("Вы и так не записаны")

    slot = await session.get(Slot, screening.slot_id)
    was_confirmed = confirmation.state == ConfirmationState.CONFIRMED

    confirmation.state = ConfirmationState.CANCELLED
    confirmation.cancelled_at = datetime.now(UTC)
    confirmation.was_late_cancel = slot.starts_at - datetime.now(UTC) < timedelta(
        hours=late_cancel_hours
    )
    await session.commit()

    if was_confirmed:
        await promote_from_waitlist(session, screening_id)

    return ConfirmResult(
        state=ConfirmationState.CANCELLED,
        place_in_queue=None,
        capacity=await _capacity(session, screening),
        confirmed=await _confirmed_count(session, screening_id),
    )


async def promote_from_waitlist(session: AsyncSession, screening_id: int) -> int:
    """Освободилось место — двигаем очередь и уведомляем (§7).

    Возвращает число переведённых: обычно один, но если вместимость подняли
    настройкой, то сколько поместится.
    """
    screening = await _lock_screening(session, screening_id)
    if screening is None:
        return 0
    capacity = await _capacity(session, screening)
    free = capacity - await _confirmed_count(session, screening_id)
    if free <= 0:
        return 0

    queue = (
        (
            await session.execute(
                sa.select(Confirmation)
                .where(
                    Confirmation.screening_id == screening_id,
                    Confirmation.state == ConfirmationState.WAITLIST,
                )
                .order_by(Confirmation.created_at)
                .limit(free)
            )
        )
        .scalars()
        .all()
    )
    for confirmation in queue:
        confirmation.state = ConfirmationState.CONFIRMED
        await notify.queue(
            session,
            confirmation.user_id,
            NotificationKind.WAITLIST_PROMOTED,
            dedup_key=f"promoted:{screening_id}:{confirmation.user_id}",
            payload={"screening_id": screening_id},
        )
    await session.commit()
    return len(queue)


async def cancel_screening(
    session: AsyncSession, screening_id: int, reason: str, actor_id: int
) -> Screening:
    """Отмена сеанса. Комментарий обязателен и уходит в уведомлении (§7)."""
    if not reason or not reason.strip():
        raise ScheduleError("Нужен комментарий: он уйдёт всем, кто собирался прийти")

    screening = await session.get(Screening, screening_id)
    if screening is None:
        raise ScheduleError("Показ не найден")
    if screening.status == ScreeningStatus.CANCELLED:
        raise ScheduleError("Показ уже отменён")

    screening.status = ScreeningStatus.CANCELLED
    screening.cancel_reason = reason.strip()
    screening.decided_by = actor_id
    screening.decided_at = datetime.now(UTC)

    await notify_affected(session, screening, NotificationKind.SCREENING_CANCELLED,
                           {"reason": reason.strip()})
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="screening",
            entity_id=screening_id,
            action="cancel",
            comment=reason.strip(),
        )
    )
    await session.commit()
    return screening


async def move_screening(
    session: AsyncSession, screening_id: int, slot_id: int, actor_id: int
) -> Screening:
    """Перенос в другой слот.

    §7: смена времени или даты сбрасывает подтверждения — доступность привязана
    к конкретному окну, и молча переносить людей нельзя. Смена только зала
    подтверждения сохраняет.
    """
    screening = await session.get(Screening, screening_id)
    if screening is None:
        raise ScheduleError("Показ не найден")

    target = await session.get(Slot, slot_id)
    if target is None or target.round_id != screening.round_id:
        raise ScheduleError("Слот не из этого цикла")
    if target.blocked:
        raise ScheduleError("Этот вечер закрыт")

    taken = await session.scalar(
        sa.select(Screening.id).where(
            Screening.slot_id == slot_id,
            Screening.id != screening_id,
            Screening.status != ScreeningStatus.CANCELLED,
        )
    )
    if taken:
        raise ScheduleError("На этот вечер уже назначен показ")

    old_slot = await session.get(Slot, screening.slot_id)
    time_changed = old_slot.starts_at != target.starts_at
    screening.slot_id = slot_id

    # Сначала уведомление, потом сброс: адресатов берут из подтверждений,
    # и удалённых уже не найти.
    await notify_affected(
        session,
        screening,
        NotificationKind.SCREENING_CHANGED,
        {"time_changed": time_changed, "starts_at": target.starts_at.isoformat()},
    )
    if time_changed:
        await reset_confirmations(session, screening)
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="screening",
            entity_id=screening_id,
            action="move",
            payload={"slot_id": slot_id, "confirmations_reset": time_changed},
        )
    )
    await session.commit()
    return screening


async def reset_confirmations(session: AsyncSession, screening: Screening) -> None:
    """Публична: ею же пользуются ручные события при переносе (§10)."""
    await session.execute(
        sa.delete(Confirmation).where(Confirmation.screening_id == screening.id)
    )


async def notify_affected(
    session: AsyncSession,
    screening: Screening,
    kind: NotificationKind,
    payload: dict,
    also_voters_for: Sequence[int] = (),
) -> None:
    """Уведомления получают только затронутые пользователи (§7).

    Публична: тем же правилом пользуются ручные события — у них нет цикла,
    но есть те, кто уже собрался прийти.

    `also_voters_for` добавляет голосовавших за перечисленные фильмы — это про
    замену фильма: узнать о ней должны и те, кого звали на прежний, и те, кто
    голосовал за новый и теперь может прийти.
    """
    users = (
        (
            await session.execute(
                sa.select(Confirmation.user_id).where(
                    Confirmation.screening_id == screening.id,
                    Confirmation.state != ConfirmationState.CANCELLED,
                )
            )
        )
        .scalars()
        .all()
    )
    if not users:
        # Подтверждений ещё нет — зовём тех, кто голосовал за фильм.
        users = (
            (
                await session.execute(
                    sa.select(FilmVote.user_id).where(
                        FilmVote.round_id == screening.round_id,
                        FilmVote.film_id == screening.film_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    audience = set(users)
    for film_id in also_voters_for:
        audience |= set(
            (
                await session.execute(
                    sa.select(FilmVote.user_id).where(
                        FilmVote.round_id == screening.round_id, FilmVote.film_id == film_id
                    )
                )
            )
            .scalars()
            .all()
        )

    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    for user_id in audience:
        await notify.queue(
            session,
            user_id,
            kind,
            dedup_key=f"{kind}:{screening.id}:{user_id}:{stamp}",
            payload={"screening_id": screening.id, **payload},
        )


async def screenings_of(session: AsyncSession, round_: Round) -> list[tuple[Screening, Film, Slot]]:
    rows = await session.execute(
        sa.select(Screening, Film, Slot)
        .join(Film, Film.id == Screening.film_id)
        .join(Slot, Slot.id == Screening.slot_id)
        .where(Screening.round_id == round_.id)
        .order_by(Slot.starts_at)
    )
    return [(s, f, sl) for s, f, sl in rows]
