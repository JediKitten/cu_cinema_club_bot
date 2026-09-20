"""Продвижение цикла по дедлайнам (§3, §17)."""

from datetime import date, timedelta

import sqlalchemy as sa

from app.models import Round, Screening, Slot
from app.models.enums import InterestKind, RoundStage, ScreeningStatus
from app.services import autopilot, cycle, voting
from app.services import rounds as rounds_service
from app.services.settings import SettingsService
from tests.test_rounds import admin
from tests.test_weights import add_interest, make_film, make_user

__all__ = ["admin"]


async def past_round(session, boss, stage: RoundStage) -> Round:
    """Цикл на неделю, все дедлайны которой давно прошли."""
    week = date.today() - timedelta(days=7)
    week -= timedelta(days=week.weekday())
    round_ = await rounds_service.open_round(session, week, boss.id)
    round_.stage = stage
    await session.commit()
    return round_


async def test_tick_opens_a_round_when_there_is_none(session):
    assert await session.scalar(sa.select(sa.func.count()).select_from(Round)) == 0

    done = await cycle.tick(session)

    assert any("открыт цикл" in line for line in done)
    assert await session.scalar(sa.select(sa.func.count()).select_from(Round)) == 1


async def test_fresh_round_does_not_race_through_all_stages(session):
    """Первый запуск не должен провести всю неделю за один проход.

    Дедлайны отсчитываются от недели перед показами: заведи цикл на ближайший
    понедельник в воскресенье вечером — и срез, автопилот, публикация
    шорт-листа и публикация расписания все окажутся в прошлом. Раньше один
    `tick` проходил их подряд, и люди получали готовое расписание, ни разу
    не проголосовав.
    """
    done = await cycle.tick(session)
    round_ = await rounds_service.active_round(session)

    assert round_ is not None
    assert round_.stage == RoundStage.COLLECTING, done
    # Срез этапа 1 у выбранной недели ещё впереди — время на отметки есть.
    values = await SettingsService(session).all()
    assert not autopilot.deadline_passed(
        round_.week_start, str(values["stage1_cut_at"]), str(values["display_timezone"])
    )


async def test_past_manual_event_becomes_completed(session):
    """Ручное событие тоже должно закрываться само.

    Завершёнными показы делало только закрытие цикла, и только свои. У ручного
    события цикла нет — оно оставалось «назначенным» навсегда и не попадало
    ни в «Что уже смотрели», ни в статистику, хотя прошло неделю назад.
    """
    from datetime import UTC, datetime

    from app.models import Screening, Slot
    from app.models.enums import ScreeningStatus
    from app.services import events

    boss = await admin(session)
    film = await make_film(session, "Бойцовский клуб")
    await session.commit()

    past = await events.create(
        session,
        starts_at=datetime.now(UTC) - timedelta(days=1),
        actor_id=boss.id,
        film_id=film.id,
    )
    upcoming = await events.create(
        session,
        starts_at=datetime.now(UTC) + timedelta(days=1),
        actor_id=boss.id,
        title="Ещё не было",
    )

    await cycle.tick(session)

    await session.refresh(past)
    await session.refresh(upcoming)
    assert past.status == ScreeningStatus.COMPLETED
    # Будущее не трогаем.
    assert upcoming.status == ScreeningStatus.SCHEDULED

    # И оно появляется в календаре прошедших.
    from app.services import analytics

    shown = await analytics.past_screenings(session)
    assert past.id in [row["screening_id"] for row in shown]

    # Показ, который ещё идёт, тоже не закрываем: слот длится три часа.
    now_running = await events.create(
        session,
        starts_at=datetime.now(UTC) - timedelta(minutes=30),
        actor_id=boss.id,
        title="Идёт прямо сейчас",
    )
    await cycle.tick(session)
    await session.refresh(now_running)
    assert now_running.status == ScreeningStatus.SCHEDULED

    assert isinstance(await session.get(Slot, past.slot_id), Slot)
    assert isinstance(await session.get(Screening, past.id), Screening)


async def test_tick_does_not_open_a_second_round(session):
    await cycle.tick(session)
    await cycle.tick(session)

    assert await session.scalar(sa.select(sa.func.count()).select_from(Round)) == 1


async def test_autopilot_collects_shortlist_after_deadline(session):
    boss = await admin(session)
    round_ = await past_round(session, boss, RoundStage.COLLECTING)

    film = await make_film(session, "Фильм")
    fan = await make_user(session, "Фанат")
    await session.commit()
    await add_interest(session, fan, film, InterestKind.SOON, 0)
    await session.commit()

    done = await cycle.tick(session)

    assert any("шорт-лист" in line for line in done)
    assert round_.stage in (RoundStage.SHORTLIST_REVIEW, RoundStage.SLOT_VOTING)


async def test_disabled_autopilot_only_suggests(session):
    """Тумблер выключен — решение всё равно считается, но не применяется (§5)."""
    boss = await admin(session)
    round_ = await past_round(session, boss, RoundStage.COLLECTING)
    await SettingsService(session).set_many({"autopilot_stage1_enabled": False}, boss.id)
    await session.commit()

    film = await make_film(session, "Фильм")
    fan = await make_user(session, "Фанат")
    await session.commit()
    await add_interest(session, fan, film, InterestKind.SOON, 0)
    await session.commit()

    await cycle.tick(session)

    assert round_.stage == RoundStage.COLLECTING

    from app.models import AutopilotProposal

    proposal = (
        await session.execute(
            sa.select(AutopilotProposal).where(AutopilotProposal.round_id == round_.id)
        )
    ).scalar_one()
    assert proposal.payload["film_ids"] == [film.id]


async def test_tick_is_idempotent(session):
    boss = await admin(session)
    round_ = await past_round(session, boss, RoundStage.COLLECTING)
    film = await make_film(session, "Фильм")
    fan = await make_user(session, "Фанат")
    await session.commit()
    await add_interest(session, fan, film, InterestKind.SOON, 0)
    await session.commit()

    await cycle.tick(session)
    stage_after_first = round_.stage
    second = await cycle.tick(session)

    # Второй проход не должен откатывать или повторять уже сделанное.
    assert round_.stage == stage_after_first or round_.stage.value > stage_after_first.value
    assert not any("шорт-лист собрал" in line for line in second)


async def test_running_round_closes_after_the_last_evening(session):
    boss = await admin(session)
    round_ = await past_round(session, boss, RoundStage.RUNNING)

    film = await make_film(session, "Фильм")
    await session.commit()
    slot = (
        await session.execute(
            sa.select(Slot).where(Slot.round_id == round_.id).order_by(Slot.starts_at)
        )
    ).scalars().first()
    session.add(
        Screening(
            round_id=round_.id,
            film_id=film.id,
            slot_id=slot.id,
            status=ScreeningStatus.SCHEDULED,
        )
    )
    await session.commit()

    done = await cycle.tick(session)

    assert any("закрыт" in line for line in done)
    assert round_.stage == RoundStage.CLOSED

    screening = (await session.execute(sa.select(Screening))).scalar_one()
    assert screening.status == ScreeningStatus.COMPLETED


async def test_week_not_finished_while_evenings_remain(session):
    boss = await admin(session)
    week = date.today() + timedelta(days=1)
    week -= timedelta(days=week.weekday())
    round_ = await rounds_service.open_round(session, week, boss.id)
    round_.stage = RoundStage.RUNNING
    await session.commit()

    await cycle.tick(session)
    assert round_.stage == RoundStage.RUNNING


async def test_published_round_starts_running_on_the_week(session):
    boss = await admin(session)
    round_ = await past_round(session, boss, RoundStage.PUBLISHED)

    await cycle.tick(session)
    assert round_.stage in (RoundStage.RUNNING, RoundStage.CLOSED)


async def test_full_path_from_collecting_to_published(session):
    """Сквозной проход: цикл доходит до опубликованного расписания сам."""
    boss = await admin(session)
    round_ = await past_round(session, boss, RoundStage.COLLECTING)

    film = await make_film(session, "Популярный")
    await session.commit()
    for i in range(6):
        user = await make_user(session, f"Зритель {i}")
        await session.commit()
        await add_interest(session, user, film, InterestKind.SOON, 0)
    await session.commit()

    # Первый проход собирает и публикует шорт-лист.
    await cycle.tick(session)
    assert round_.stage == RoundStage.SLOT_VOTING

    slots = (
        (
            await session.execute(
                sa.select(Slot).where(Slot.round_id == round_.id).order_by(Slot.starts_at)
            )
        )
        .scalars()
        .all()
    )
    users = (
        (await session.execute(sa.select(sa.text("id FROM users")))).scalars().all()
    )
    for user_id in users:
        await voting.set_votes(session, round_, user_id, [film.id])
        await voting.set_availability(session, round_, user_id, [slots[2].id])

    # Второй проход расставляет и публикует расписание.
    await cycle.tick(session)
    assert round_.stage in (RoundStage.PUBLISHED, RoundStage.RUNNING, RoundStage.CLOSED)

    screening = (await session.execute(sa.select(Screening))).scalars().first()
    assert screening is not None
    assert screening.film_id == film.id


async def test_next_round_opens_while_the_current_week_is_still_running(session):
    """Следующую неделю готовят во время текущей, а не после неё.

    Сроки подготовки — срез в среду, голосование до воскресенья — приходятся
    ровно на идущую неделю показов. Пока новый цикл ждал закрытия старого,
    он заводился в воскресенье ночью, когда среда уже прошла, и `tick`
    перескакивал через неделю: клуб молча оставался без кино и без
    приглашения голосовать.
    """
    boss = await admin(session)
    this_week = date.today() - timedelta(days=date.today().weekday())
    running = await rounds_service.open_round(session, this_week, boss.id)
    running.stage = RoundStage.RUNNING
    await session.commit()

    await cycle.tick(session)

    prepared = await rounds_service.preparing_round(session)
    assert prepared is not None, "следующий цикл не завёлся"
    assert prepared.week_start > this_week
    # Идущая неделя при этом остаётся идущей: её не тронули.
    await session.refresh(running)
    assert running.stage == RoundStage.RUNNING


async def test_a_week_already_scheduled_is_not_prepared_twice(session):
    """Опубликованное расписание — не повод собирать шорт-лист заново.

    `open_round` идемпотентна по неделе и молча вернула бы существующий цикл;
    если бы `tick` взял его как «готовящийся», он погнал бы объявленную
    неделю по этапам второй раз.
    """
    boss = await admin(session)
    next_week = rounds_service.next_week_start()
    published = await rounds_service.open_round(session, next_week, boss.id)
    published.stage = RoundStage.PUBLISHED
    await session.commit()

    await cycle.tick(session)

    await session.refresh(published)
    assert published.stage in (RoundStage.PUBLISHED, RoundStage.RUNNING)
    prepared = await rounds_service.preparing_round(session)
    assert prepared is not None and prepared.week_start > next_week


async def test_finished_week_closes_even_while_the_next_one_is_being_prepared(session):
    """Закрытие идущей недели не должно зависеть от того, чем занят цикл рядом."""
    boss = await admin(session)
    old = await past_round(session, boss, RoundStage.RUNNING)
    await cycle.tick(session)

    await session.refresh(old)
    assert old.stage == RoundStage.CLOSED
    assert (await rounds_service.preparing_round(session)) is not None


# --- Предупреждение об автопилоте -------------------------------------------


async def autopilot_warning_setup(session, stage: RoundStage):
    """Цикл на будущей неделе плюс админ, которому есть что сообщить."""
    from app.services import rounds as rounds_service

    boss = await admin(session)
    round_ = await rounds_service.open_round(session, rounds_service.next_week_start(), boss.id)
    round_.stage = stage
    await session.commit()
    return round_, boss


async def deadline_of(session, round_, setting: str):
    from app.services import rounds as rounds_service

    values = await SettingsService(session).all()
    return rounds_service.deadline_moment(
        round_.week_start, str(values[setting]), str(values["display_timezone"])
    )


async def test_admin_is_warned_an_hour_before_the_shortlist_is_picked(session):
    """Автопилот решает сам, и раньше админ узнавал об этом постфактум —
    из «автопилот отработал». Решение остаётся за человеком только пока он
    успевает его принять."""
    from datetime import timedelta

    import sqlalchemy as sa

    from app.models import Notification
    from app.models.enums import NotificationKind
    from app.services import reminders

    round_, boss = await autopilot_warning_setup(session, RoundStage.COLLECTING)
    deadline = await deadline_of(session, round_, "stage1_autopilot_at")

    # За два часа — рано, молчим.
    assert await reminders.warn_before_autopilot(session, deadline - timedelta(hours=2)) == 0
    # Уже после — поздно, автопилот отработал.
    assert await reminders.warn_before_autopilot(session, deadline + timedelta(minutes=1)) == 0

    assert await reminders.warn_before_autopilot(session, deadline - timedelta(minutes=30)) == 1
    # Повторный проход не шлёт второго письма.
    assert await reminders.warn_before_autopilot(session, deadline - timedelta(minutes=20)) == 0

    payload = (
        await session.execute(
            sa.select(Notification.payload).where(
                Notification.user_id == boss.id,
                Notification.kind == NotificationKind.ADMIN_AUTOPILOT_SOON,
            )
        )
    ).scalar_one()
    assert "шорт-лист" in payload["what"] and payload["enabled"] is True


async def test_the_warning_names_the_film_of_the_week_on_the_second_stage(session):
    from datetime import timedelta

    import sqlalchemy as sa

    from app.models import Notification
    from app.models.enums import NotificationKind
    from app.services import reminders

    round_, boss = await autopilot_warning_setup(session, RoundStage.SLOT_VOTING)
    deadline = await deadline_of(session, round_, "stage2_autopilot_at")

    assert await reminders.warn_before_autopilot(session, deadline - timedelta(minutes=10)) == 1
    payload = (
        await session.execute(
            sa.select(Notification.payload).where(
                Notification.kind == NotificationKind.ADMIN_AUTOPILOT_SOON
            )
        )
    ).scalar_one()
    assert "фильм недели" in payload["what"]


async def test_a_switched_off_autopilot_is_the_louder_news(session):
    """Выключенный тумблер значит, что не произойдёт вообще ничего, —
    и знать об этом админу важнее, чем про сработавший автопилот."""
    from datetime import timedelta

    from app.models.enums import NotificationKind
    from app.services import notify, reminders

    round_, _ = await autopilot_warning_setup(session, RoundStage.COLLECTING)
    await SettingsService(session).set_many({"autopilot_stage1_enabled": False}, None)
    await session.commit()

    deadline = await deadline_of(session, round_, "stage1_autopilot_at")
    assert await reminders.warn_before_autopilot(session, deadline - timedelta(minutes=5)) == 1

    text = notify.render(
        NotificationKind.ADMIN_AUTOPILOT_SOON,
        None,
        "",
        {"what": "соберёт шорт-лист недели", "enabled": False, "week_start": "2026-10-05"},
    )
    assert text is not None and "не произойдёт ничего" in text
