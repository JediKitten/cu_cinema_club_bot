"""Автопилоты этапов 1 и 2 (§5, §6)."""

from datetime import UTC, date, datetime

import sqlalchemy as sa

from app.models import Screening, ShortlistItem, Slot
from app.models.enums import InterestKind, RoundStage, ScreeningStatus
from app.services import autopilot, voting
from app.services import rounds as rounds_service
from app.services.settings import SettingsService
from tests.test_rounds import admin
from tests.test_weights import add_interest, make_film, make_user

__all__ = ["admin"]


async def test_deadline_relates_to_the_week_before_screenings(session):
    """Дедлайны считаются от недели, предшествующей показам (§3)."""
    week = date(2026, 9, 7)  # понедельник недели показов

    # Среда 20:00 предыдущей недели — 2 сентября.
    before = datetime(2026, 9, 2, 18, 0, tzinfo=UTC)
    after = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)

    assert not autopilot.deadline_passed(week, "2 20:00", "UTC", before)
    assert autopilot.deadline_passed(week, "2 20:00", "UTC", after)


async def test_shortlist_autopilot_uses_coverage_and_threshold(session):
    """Берёт рейтинг по покрытию и отбрасывает всё ниже порога (§5)."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)

    strong = await make_film(session, "Сильный")
    weak = await make_film(session, "Слабый")
    fan = await make_user(session, "Фанат")
    stale = await make_user(session, "Давний")
    await session.commit()

    await add_interest(session, fan, strong, InterestKind.SOON, 0)
    # Очень старое «Желаемое» — вес у пола, ниже порога.
    await add_interest(session, stale, weak, InterestKind.WISHLIST, 10_000)
    await session.commit()

    film_ids = await autopilot.propose_shortlist(session, round_)
    assert film_ids == [strong.id]


async def test_low_activity_flag_when_not_enough_films(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)

    film = await make_film(session, "Единственный")
    fan = await make_user(session, "Фанат")
    await session.commit()
    await add_interest(session, fan, film, InterestKind.SOON, 0)
    await session.commit()

    # Подсказка флаг не поднимает: на свежем цикле отметок ещё нет, и «низкая
    # активность» была бы ложной тревогой.
    await autopilot.propose_shortlist(session, round_)
    assert round_.low_activity is False

    # А когда автопилот действительно решает — флаг уместен: размер шорт-листа
    # по умолчанию 5, набрали один.
    await autopilot.propose_shortlist(session, round_, deciding=True)
    assert round_.low_activity is True


async def test_apply_shortlist_only_when_admin_did_nothing(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    film = await make_film(session, "Фильм")
    fan = await make_user(session, "Фанат")
    await session.commit()
    await add_interest(session, fan, film, InterestKind.SOON, 0)
    await session.commit()

    assert await autopilot.apply_shortlist(session, round_) == 1
    assert round_.stage == RoundStage.SHORTLIST_REVIEW

    # Повторный запуск на уже собранном шорт-листе ничего не делает.
    assert await autopilot.apply_shortlist(session, round_) == 0


async def test_schedule_autopilot_maximises_total_attendance(session):
    """Задача о назначениях: суммарная явка должна быть максимальной (§6)."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    films = [await make_film(session, f"Фильм {i}") for i in range(2)]
    await session.commit()
    await rounds_service.set_shortlist(session, round_, [f.id for f in films], boss.id)
    await rounds_service.publish_shortlist(session, round_, boss.id)

    slots = (
        (
            await session.execute(
                sa.select(Slot).where(Slot.round_id == round_.id).order_by(Slot.starts_at)
            )
        )
        .scalars()
        .all()
    )
    monday, tuesday = slots[0], slots[1]

    # Кворум по умолчанию 5, поэтому нужны группы побольше.
    # Фильм 0 популярен в понедельник, фильм 1 — во вторник.
    for i in range(6):
        user = await make_user(session, f"Пн-{i}")
        await session.commit()
        await voting.set_votes(session, round_, user.id, [films[0].id])
        await voting.set_availability(session, round_, user.id, [monday.id])
    for i in range(7):
        user = await make_user(session, f"Вт-{i}")
        await session.commit()
        await voting.set_votes(session, round_, user.id, [films[1].id])
        await voting.set_availability(session, round_, user.id, [tuesday.id])

    proposal = await autopilot.propose_schedule(session, round_)
    placement = {a.film_id: a.slot_id for a in proposal}

    assert placement[films[0].id] == monday.id
    assert placement[films[1].id] == tuesday.id


async def test_slots_below_quorum_are_left_empty(session):
    """Показ ради двух человек не нужен (§6)."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    film = await make_film(session, "Нишевый")
    await session.commit()
    await rounds_service.set_shortlist(session, round_, [film.id], boss.id)
    await rounds_service.publish_shortlist(session, round_, boss.id)

    slots = (
        (await session.execute(sa.select(Slot).where(Slot.round_id == round_.id)))
        .scalars()
        .all()
    )
    # Всего двое при кворуме 5.
    for i in range(2):
        user = await make_user(session, f"Зритель {i}")
        await session.commit()
        await voting.set_votes(session, round_, user.id, [film.id])
        await voting.set_availability(session, round_, user.id, [slots[0].id])

    assert await autopilot.propose_schedule(session, round_) == []


async def test_apply_schedule_creates_screenings(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    film = await make_film(session, "Популярный")
    await session.commit()
    await rounds_service.set_shortlist(session, round_, [film.id], boss.id)
    await rounds_service.publish_shortlist(session, round_, boss.id)

    slots = (
        (
            await session.execute(
                sa.select(Slot).where(Slot.round_id == round_.id).order_by(Slot.starts_at)
            )
        )
        .scalars()
        .all()
    )
    for i in range(6):
        user = await make_user(session, f"Зритель {i}")
        await session.commit()
        await voting.set_votes(session, round_, user.id, [film.id])
        await voting.set_availability(session, round_, user.id, [slots[1].id])

    assert await autopilot.apply_schedule(session, round_, boss.id) == 1

    screening = (
        await session.execute(
            sa.select(Screening).where(Screening.status == ScreeningStatus.SCHEDULED)
        )
    ).scalar_one()
    assert screening.film_id == film.id
    assert screening.expected_attendance == 6


async def test_monday_is_used_last(session):
    """Между публикацией и понедельничным показом меньше суток (§3)."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    films = [await make_film(session, f"Фильм {i}") for i in range(2)]
    await session.commit()
    await rounds_service.set_shortlist(session, round_, [f.id for f in films], boss.id)
    await rounds_service.publish_shortlist(session, round_, boss.id)

    slots = (
        (
            await session.execute(
                sa.select(Slot).where(Slot.round_id == round_.id).order_by(Slot.starts_at)
            )
        )
        .scalars()
        .all()
    )
    monday, wednesday = slots[0], slots[2]

    # Обе группы одинакового размера, но каждая свободна в свой вечер.
    for i in range(6):
        user = await make_user(session, f"А-{i}")
        await session.commit()
        await voting.set_votes(session, round_, user.id, [films[0].id])
        await voting.set_availability(session, round_, user.id, [monday.id])
    for i in range(6):
        user = await make_user(session, f"Б-{i}")
        await session.commit()
        await voting.set_votes(session, round_, user.id, [films[1].id])
        await voting.set_availability(session, round_, user.id, [wednesday.id])

    proposal = await autopilot.propose_schedule(session, round_)
    # Понедельничный показ идёт последним в списке предложений.
    assert proposal[-1].slot_id == monday.id


async def test_proposal_is_saved_for_the_admin_to_see(session):
    """Автопилот считает решение всегда — оно показывается рядом как подсказка (§5)."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    film = await make_film(session, "Фильм")
    fan = await make_user(session, "Фанат")
    await session.commit()
    await add_interest(session, fan, film, InterestKind.SOON, 0)
    await session.commit()

    await autopilot.propose_shortlist(session, round_)
    await autopilot.propose_shortlist(session, round_)  # повторно — не дублируем

    from app.models import AutopilotProposal

    rows = (
        (
            await session.execute(
                sa.select(AutopilotProposal).where(AutopilotProposal.round_id == round_.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].payload["film_ids"] == [film.id]
    assert "computed_at" in rows[0].payload


async def test_shortlist_replaced_not_appended(session):
    """Автопилот заменяет шорт-лист целиком, а не дописывает к прежнему."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    film = await make_film(session, "Фильм")
    fan = await make_user(session, "Фанат")
    await session.commit()
    await add_interest(session, fan, film, InterestKind.SOON, 0)
    await session.commit()

    await autopilot.apply_shortlist(session, round_)
    round_.stage = RoundStage.COLLECTING
    await session.commit()
    await autopilot.apply_shortlist(session, round_)

    total = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ShortlistItem)
        .where(ShortlistItem.round_id == round_.id)
    )
    assert total == 1


async def test_autopilot_can_be_switched_off(session):
    """Тумблеры автопилота — параметры §13, а не константы."""
    values = await SettingsService(session).all()
    assert values["autopilot_stage1_enabled"] is True
    assert values["autopilot_stage2_enabled"] is True
