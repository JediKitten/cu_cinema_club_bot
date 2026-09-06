"""Этап 2: голосование за фильмы и вечера, матрица для админа (§6)."""

from datetime import date

import pytest
import sqlalchemy as sa

from app.models import Availability, FilmVote, Slot
from app.models.enums import RoundStage
from app.services import rounds as rounds_service
from app.services import voting
from app.services.voting import VotingError
from tests.conftest import set_shortlist
from tests.test_rounds import admin
from tests.test_weights import make_film, make_user

__all__ = ["admin"]  # фикстура переиспользуется из test_rounds


async def prepared_round(session, film_count: int = 3):
    """Цикл, доведённый до открытого голосования."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    films = [await make_film(session, f"Фильм {i}") for i in range(film_count)]
    await session.commit()

    await set_shortlist(session, round_, [f.id for f in films], boss.id)
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
    return round_, films, slots, boss


async def test_voting_closed_until_shortlist_published(session):
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)

    with pytest.raises(VotingError, match="закрыто"):
        voting.ensure_open(round_)


async def test_votes_replace_previous_choice(session):
    round_, films, _, _ = await prepared_round(session)
    voter = await make_user(session, "Голосующий")
    await session.commit()

    await voting.set_votes(session, round_, voter.id, [films[0].id, films[1].id])
    assert await voting.my_votes(session, round_, voter.id) == sorted([films[0].id, films[1].id])

    # Выбор — состояние, а не история: второй заход заменяет первый целиком.
    await voting.set_votes(session, round_, voter.id, [films[2].id])
    assert await voting.my_votes(session, round_, voter.id) == [films[2].id]
    assert await session.scalar(sa.select(sa.func.count()).select_from(FilmVote)) == 1


async def test_votes_limited_to_shortlist(session):
    round_, _, _, _ = await prepared_round(session)
    outsider = await make_film(session, "Не в шорт-листе")
    voter = await make_user(session, "Голосующий")
    await session.commit()

    with pytest.raises(VotingError, match="шорт-листа"):
        await voting.set_votes(session, round_, voter.id, [outsider.id])


async def test_availability_rejects_blocked_evening(session):
    round_, _, slots, boss = await prepared_round(session)
    voter = await make_user(session, "Голосующий")
    await session.commit()

    await rounds_service.set_slot_blocked(session, slots[0].id, True, "пары", boss.id)

    with pytest.raises(VotingError, match="недоступен"):
        await voting.set_availability(session, round_, voter.id, [slots[0].id])

    await voting.set_availability(session, round_, voter.id, [slots[1].id])
    assert await voting.my_availability(session, round_, voter.id) == [slots[1].id]


async def test_duplicates_are_collapsed(session):
    round_, films, _, _ = await prepared_round(session)
    voter = await make_user(session, "Голосующий")
    await session.commit()

    await voting.set_votes(session, round_, voter.id, [films[0].id, films[0].id])
    assert await session.scalar(sa.select(sa.func.count()).select_from(FilmVote)) == 1


async def test_matrix_counts_only_people_free_that_evening(session):
    """Ячейка — те, кто одновременно выбрал фильм и свободен в этот вечер (§6)."""
    round_, films, slots, _ = await prepared_round(session)
    monday, tuesday = slots[0], slots[1]

    anna = await make_user(session, "Аня")  # фильм 0, свободна в понедельник
    boris = await make_user(session, "Борис")  # фильм 0, свободен во вторник
    vera = await make_user(session, "Вера")  # фильм 0, свободна оба вечера
    await session.commit()

    for user, free in ((anna, [monday]), (boris, [tuesday]), (vera, [monday, tuesday])):
        await voting.set_votes(session, round_, user.id, [films[0].id])
        await voting.set_availability(session, round_, user.id, [s.id for s in free])

    matrix = await voting.build_matrix(session, round_)
    assert matrix.cell(films[0].id, monday.id) == 2  # Аня и Вера
    assert matrix.cell(films[0].id, tuesday.id) == 2  # Борис и Вера
    assert matrix.cell(films[1].id, monday.id) == 0  # за этот фильм не голосовали

    assert matrix.film_votes[films[0].id] == 3
    assert matrix.slot_free[monday.id] == 2
    assert matrix.slot_free[tuesday.id] == 2


async def test_matrix_counts_voters_without_evening(session):
    """Голос за фильм без свободного вечера ни на что не влияет — админ должен
    видеть, сколько таких (§6)."""
    round_, films, slots, _ = await prepared_round(session)

    useful = await make_user(session, "С вечером")
    useless = await make_user(session, "Без вечера")
    await session.commit()

    await voting.set_votes(session, round_, useful.id, [films[0].id])
    await voting.set_availability(session, round_, useful.id, [slots[0].id])
    await voting.set_votes(session, round_, useless.id, [films[0].id])

    matrix = await voting.build_matrix(session, round_)
    assert matrix.film_votes[films[0].id] == 2
    assert matrix.cell(films[0].id, slots[0].id) == 1
    assert matrix.voters_without_evening == 1


async def test_matrix_ignores_blocked_evenings(session):
    round_, films, slots, boss = await prepared_round(session)
    voter = await make_user(session, "Голосующий")
    await session.commit()

    await voting.set_votes(session, round_, voter.id, [films[0].id])
    await voting.set_availability(session, round_, voter.id, [slots[0].id, slots[1].id])

    # Вечер закрыли уже после голосования — из матрицы он должен исчезнуть.
    await rounds_service.set_slot_blocked(session, slots[0].id, True, "мероприятие", boss.id)

    matrix = await voting.build_matrix(session, round_)
    assert slots[0].id not in matrix.slot_ids
    assert matrix.cell(films[0].id, slots[0].id) == 0
    assert matrix.cell(films[0].id, slots[1].id) == 1


async def test_availability_replaces_previous(session):
    round_, _, slots, _ = await prepared_round(session)
    voter = await make_user(session, "Голосующий")
    await session.commit()

    await voting.set_availability(session, round_, voter.id, [slots[0].id, slots[1].id])
    await voting.set_availability(session, round_, voter.id, [slots[2].id])
    assert await voting.my_availability(session, round_, voter.id) == [slots[2].id]
    assert await session.scalar(sa.select(sa.func.count()).select_from(Availability)) == 1


async def test_voting_stops_after_stage_moves_on(session):
    round_, films, _, _ = await prepared_round(session)
    voter = await make_user(session, "Опоздавший")
    await session.commit()

    round_.stage = RoundStage.SCHEDULE_REVIEW
    await session.commit()

    with pytest.raises(VotingError, match="закрыто"):
        await voting.set_votes(session, round_, voter.id, [films[0].id])
