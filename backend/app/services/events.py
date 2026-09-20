"""Ручные события (§10, расширение по просьбе клуба).

Администратор назначает показ или встречу на любое время, в обход алгоритма.
Такое событие не принадлежит недельному циклу и не участвует в его правилах:
фильм может быть ещё не объявлен, а время — любым, не только вечером в 19:00.
"""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Film, Hall, Round, Screening, ShortlistItem, Slot
from app.models.enums import NotificationKind, ScreeningStatus
from app.services import schedule as schedule_service
from app.services.rounds import ensure_hall


class EventError(ValueError):
    """Причину показываем администратору как есть."""


async def create(
    session: AsyncSession,
    *,
    starts_at: datetime,
    actor_id: int,
    film_id: int | None = None,
    title: str | None = None,
    note: str | None = None,
    duration_min: int = 180,
    hall_id: int | None = None,
    in_english: bool = False,
    registration_url: str | None = None,
) -> Screening:
    """Заводит событие вне цикла.

    Без фильма событие обязано иметь заголовок — иначе в расписании появится
    строка, о которой нельзя сказать вообще ничего.
    """
    if film_id is None and not (title or "").strip():
        raise EventError("Укажите фильм или заголовок события")

    if film_id is not None and await session.get(Film, film_id) is None:
        raise EventError("Фильм не найден")

    if starts_at.tzinfo is None:
        raise EventError("Время должно быть с часовым поясом")

    hall = await session.get(Hall, hall_id) if hall_id else await ensure_hall(session)
    if hall is None:
        raise EventError("Зал не найден")

    await _check_free(session, hall.id, starts_at)

    slot = Slot(round_id=None, hall_id=hall.id, starts_at=starts_at, duration_min=duration_min)
    session.add(slot)
    await session.flush()

    event = Screening(
        round_id=None,
        film_id=film_id,
        slot_id=slot.id,
        is_manual=True,
        in_english=in_english,
        registration_url=(registration_url or "").strip() or None,
        title=(title or "").strip() or None,
        note=(note or "").strip() or None,
        decided_by=actor_id,
        decided_at=datetime.now(UTC),
    )
    session.add(event)
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="screening",
            action="create_manual",
            payload={"starts_at": starts_at.isoformat(), "film_id": film_id, "title": title},
        )
    )
    await session.commit()
    return event


async def _check_free(
    session: AsyncSession, hall_id: int, starts_at: datetime, except_id: int | None = None
) -> None:
    busy = await session.scalar(
        sa.select(Screening.id)
        .join(Slot, Slot.id == Screening.slot_id)
        .where(
            Slot.hall_id == hall_id,
            Slot.starts_at == starts_at,
            Screening.id != (except_id or -1),
            Screening.status != ScreeningStatus.CANCELLED,
        )
    )
    if busy:
        raise EventError("На это время в зале уже что-то назначено")


# Что администратор вправе поменять у уже назначенного события.
EDITABLE = (
    "starts_at",
    "duration_min",
    "film_id",
    "title",
    "note",
    "in_english",
    "registration_url",
)

# Что можно поменять у показа, назначенного циклом. Фильм — нельзя: его выбрало
# голосование, и подменять его здесь значило бы обойти цикл целиком. Время —
# можно: зал бывает занят, ведущий болеет, и переносить показ приходится
# в том числе на час, которого в сетке вечеров нет. Вечер при этом сдвигается
# вместе с показом, а подтверждения сбрасываются — доступность люди отмечали
# под конкретный вечер.
# Что у показа из цикла правит администратор. Фильм — тоже: не любой, а другой
# из шорт-листа этой же недели. Голосование выбирало список, автопилот взял
# из него один по ожидаемой явке на конкретный вечер — и если у клуба есть
# причина поставить соседний (не дали права, не нашлась копия, ведущий готов
# говорить про другое), это не обход голосования, а выбор внутри него.
EDITABLE_IN_ROUND = (
    "film_id",
    "starts_at",
    "duration_min",
    "note",
    "in_english",
    "registration_url",
)


async def _already_in_round(
    session: AsyncSession, event: Screening, film_id: int
) -> bool:
    """Тот же фильм дважды за неделю — нарушение §6, и база его не пропустит
    (частичный индекс). Ловим здесь, чтобы отдать причину, а не пятисотку."""
    twin = await session.scalar(
        sa.select(Screening.id).where(
            Screening.round_id == event.round_id,
            Screening.film_id == film_id,
            Screening.id != event.id,
            Screening.status != ScreeningStatus.CANCELLED,
        )
    )
    return twin is not None


async def _slot_for(
    session: AsyncSession, event: Screening, slot: Slot, starts_at: datetime
) -> Slot:
    """Куда переселить показ на новое время.

    У недели цикла вечера уже нарезаны, и время соседнего вечера в сетке
    занято им же. Тащить туда свой слот нельзя: «цикл + зал + время»
    уникально, и правка падала на ограничении базы — администратор получал
    пятисотку вместо переноса, причём ровно в самом обычном случае, когда
    показ двигают на час внутри той же недели.

    Поэтому: есть вечер с таким временем — показ переезжает в него, прежний
    остаётся свободным. Нет — двигаем свой слот, как и раньше: заводить новый
    значило бы плодить пустые окна в расписании.
    """
    if slot.round_id is None:
        # Ручное событие: слот заведён под него одно и ничьим вечером не был.
        slot.starts_at = starts_at
        return slot

    sibling = (
        await session.execute(
            sa.select(Slot).where(
                Slot.round_id == slot.round_id,
                Slot.hall_id == slot.hall_id,
                Slot.starts_at == starts_at,
                Slot.id != slot.id,
            )
        )
    ).scalar_one_or_none()

    if sibling is None:
        slot.starts_at = starts_at
        return slot
    if sibling.blocked:
        raise EventError("Этот вечер закрыт — снимите блокировку или выберите другое время")

    event.slot_id = sibling.id
    return sibling


async def update(
    session: AsyncSession,
    event_id: int,
    actor_id: int,
    changes: dict,
    keep_confirmations: bool = False,
) -> Screening:
    """Правит уже назначенное событие.

    Приходит только то, что действительно меняли: отсутствие ключа и `None`
    различаются — иначе снять фильм с анонса было бы нельзя, не затерев заодно
    подпись. Смена времени сбрасывает подтверждения, как и перенос показа в
    цикле (§7): доступность привязана к конкретному вечеру.

    `keep_confirmations` оставляет записи на месте — для случая, когда время
    поправили сразу после анонса и терять семь «приду» из-за опечатки в дате
    жалко. Решает администратор: он один знает, тот же это вечер по сути или
    уже другой. Пришедшее сообщение тогда просит отменить запись тех, кому
    новое время не подходит, вместо того чтобы просить отметиться заново.
    """
    event = await session.get(Screening, event_id)
    if event is None:
        raise EventError("Событие не найдено")
    if event.status == ScreeningStatus.CANCELLED:
        raise EventError("Событие отменено, править его нечего")

    allowed = set(EDITABLE if event.is_manual else EDITABLE_IN_ROUND)
    unknown = set(changes) - allowed
    if unknown:
        if event.is_manual:
            raise EventError(f"Нельзя менять: {', '.join(sorted(unknown))}")
        raise EventError(f"У показа из цикла нельзя менять: {', '.join(sorted(unknown))}")

    slot = await session.get(Slot, event.slot_id)
    film_id = changes.get("film_id", event.film_id)
    title = changes.get("title", event.title)
    if film_id is None and not (title or "").strip():
        raise EventError("Укажите фильм или заголовок события")
    if film_id is not None and await session.get(Film, film_id) is None:
        raise EventError("Фильм не найден")

    film_changed = "film_id" in changes and film_id != event.film_id
    was_film_id = event.film_id
    # Название прежнего фильма нужно сообщению о замене: «вместо чего» человеку
    # важнее, чем «что теперь» — он шёл на конкретное кино.
    was_title = None
    if film_changed and was_film_id is not None:
        was = await session.get(Film, was_film_id)
        was_title = was.title_ru if was else None
    if film_changed and event.round_id is not None:
        # Показ из цикла: заменить можно только на фильм того же шорт-листа.
        # Поставить что угодно значило бы отменить голосование задним числом —
        # люди выбирали из пяти названий, а пришли бы на шестое.
        shortlisted = await session.scalar(
            sa.select(ShortlistItem.id).where(
                ShortlistItem.round_id == event.round_id, ShortlistItem.film_id == film_id
            )
        )
        if shortlisted is None:
            raise EventError(
                "Заменить можно только на фильм из шорт-листа этой недели — "
                "за них и голосовали"
            )
        if await _already_in_round(session, event, film_id):
            raise EventError("Этот фильм уже стоит в расписании недели")

    # Фильм появился там, где его не было: это анонс, а не правка. Считаем до
    # присвоения — после event.film_id уже новый.
    revealed = event.film_id is None and film_id is not None
    time_changed = False
    if "starts_at" in changes:
        starts_at = changes["starts_at"]
        if starts_at.tzinfo is None:
            raise EventError("Время должно быть с часовым поясом")
        time_changed = starts_at != slot.starts_at
        if time_changed:
            await _check_free(session, slot.hall_id, starts_at, except_id=event.id)
            slot = await _slot_for(session, event, slot, starts_at)
    if "duration_min" in changes:
        slot.duration_min = changes["duration_min"]

    event.film_id = film_id
    event.title = (title or "").strip() or None
    if "note" in changes:
        event.note = (changes["note"] or "").strip() or None
    if "in_english" in changes:
        event.in_english = bool(changes["in_english"])
    if "registration_url" in changes:
        event.registration_url = (changes["registration_url"] or "").strip() or None
    event.decided_by = actor_id
    event.decided_at = datetime.now(UTC)

    if film_changed and event.round_id is not None:
        # Ожидаемая явка — ячейка матрицы «фильм × вечер». У нового фильма она
        # своя, и оставлять чужое число нельзя: по нему предупреждают о недоборе.
        round_ = await session.get(Round, event.round_id)
        matrix = await schedule_service.build_matrix(session, round_)
        event.expected_attendance = matrix.cell(film_id, slot.id)

    if time_changed or film_changed:
        # Молча переносить или подменять фильм нельзя: люди уже собрались прийти.
        # Уведомление раньше сброса: адресатов берут из подтверждений.
        # При замене зовём ещё и голосовавших — за прежний фильм, потому что
        # звали их именно на него, и за новый, потому что теперь их вечер.
        await schedule_service.notify_affected(
            session,
            event,
            NotificationKind.SCREENING_CHANGED,
            {
                "time_changed": time_changed,
                "revealed": revealed,
                "film_changed": film_changed,
                "was_film": was_title,
                "kept": keep_confirmations,
                "starts_at": slot.starts_at.isoformat(),
            },
            also_voters_for=(
                [f for f in (was_film_id, film_id) if f is not None] if film_changed else ()
            ),
        )
    if time_changed and not keep_confirmations:
        await schedule_service.reset_confirmations(session, event)

    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="screening",
            entity_id=event.id,
            action="edit_manual",
            payload={
                "keep_confirmations": keep_confirmations,
                **{
                    key: (value.isoformat() if isinstance(value, datetime) else value)
                    for key, value in changes.items()
                },
            },
        )
    )
    await session.commit()
    return event


async def upcoming(
    session: AsyncSession, within_days: int | None = None, manual_only: bool = False
) -> list[Screening]:
    """Всё, что клубу предстоит: и ручные события, и показы цикла.

    Раньше список был только из ручных, и назначенный голосованием фильм недели
    в него не попадал — а прикладывать к вечеру ссылку на регистрацию или
    помечать его английским приходится независимо от того, откуда он взялся.
    Что у показа можно поменять, решает `update`: у фильма недели время и сам
    фильм остаются за циклом.

    По умолчанию без горизонта: событие могут анонсировать за полгода, и
    администратор, который его не видит, не может ни поправить, ни отменить.
    Горизонт остаётся параметром для тех, кому нужны только ближайшие.
    """
    conditions = [
        Screening.status != ScreeningStatus.CANCELLED,
        # Шесть часов назад, а не «сейчас»: идущее сегодня событие ещё актуально.
        Slot.starts_at >= datetime.now(UTC) - timedelta(hours=6),
    ]
    if manual_only:
        conditions.append(Screening.is_manual.is_(True))
    if within_days is not None:
        conditions.append(Slot.starts_at <= datetime.now(UTC) + timedelta(days=within_days))

    rows = await session.execute(
        sa.select(Screening)
        .join(Slot, Slot.id == Screening.slot_id)
        .where(*conditions)
        .order_by(Slot.starts_at)
    )
    return list(rows.scalars())


async def reveal(
    session: AsyncSession, event_id: int, film_id: int, actor_id: int
) -> Screening:
    """Раскрывает фильм у объявленного заранее события.

    Именно ради этого события и заводят «ждите анонса»: время уже известно,
    а название объявляют позже. Частный случай правки — и проверки, и
    уведомление тем, кто уже собрался, те же самые.
    """
    return await update(session, event_id, actor_id, {"film_id": film_id})
