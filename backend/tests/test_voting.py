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


async def test_button_toggles_a_single_vote(session):
    """Кнопка под уведомлением ставит и снимает ровно один голос."""
    round_, films, _, _ = await prepared_round(session)
    voter = await make_user(session, "Зритель")
    await session.commit()

    on, chosen = await voting.toggle_vote(session, round_, voter.id, films[0].id)
    assert on and chosen == [films[0].id]

    on, chosen = await voting.toggle_vote(session, round_, voter.id, films[1].id)
    assert on and chosen == sorted([films[0].id, films[1].id])

    off, chosen = await voting.toggle_vote(session, round_, voter.id, films[0].id)
    assert not off and chosen == [films[1].id]


async def test_button_does_not_wipe_a_neighbouring_vote(session):
    """Нажатия приходят подряд, и голос соседнего фильма переписывать нечем:
    `toggle_vote` трогает одну строку, а не весь набор."""
    round_, films, _, _ = await prepared_round(session)
    voter = await make_user(session, "Зритель")
    await session.commit()
    await voting.set_votes(session, round_, voter.id, [films[0].id, films[1].id])

    await voting.toggle_vote(session, round_, voter.id, films[2].id)

    assert await voting.my_votes(session, round_, voter.id) == sorted(
        [films[0].id, films[1].id, films[2].id]
    )


async def test_button_refuses_a_film_outside_the_shortlist(session):
    round_, films, _, _ = await prepared_round(session)
    voter = await make_user(session, "Зритель")
    stranger = await make_film(session, "Не в списке")
    await session.commit()

    with pytest.raises(VotingError, match="шорт-лист"):
        await voting.toggle_vote(session, round_, voter.id, stranger.id)


async def test_button_is_dead_after_voting_closes(session):
    round_, films, _, _ = await prepared_round(session)
    voter = await make_user(session, "Зритель")
    await session.commit()

    round_.stage = RoundStage.SCHEDULE_REVIEW
    await session.commit()

    with pytest.raises(VotingError, match="закрыто"):
        await voting.toggle_vote(session, round_, voter.id, films[0].id)


async def _special_week(session):
    """Хэллоуин: время назначено заранее, клуб выбирает только фильм."""
    boss = await admin(session)
    round_ = await rounds_service.open_round(session, date(2026, 9, 7), boss.id)
    films = [await make_film(session, f"Хоррор {i}") for i in range(3)]
    slots = list(
        (await session.execute(sa.select(Slot).where(Slot.round_id == round_.id))).scalars()
    )
    for slot in slots[1:]:
        slot.blocked = True
    round_.theme_note = "🎃 Особый показ на Хэллоуин"
    round_.fixed_slot = True
    await session.commit()
    await set_shortlist(session, round_, [f.id for f in films], boss.id)
    return round_, films, slots[0], boss


async def test_fixed_slot_counts_a_film_vote_as_coming_that_evening(session):
    """Вечер никто не выбирает — голос за фильм и есть согласие прийти."""
    round_, films, slot, boss = await _special_week(session)
    await rounds_service.publish_shortlist(session, round_, boss.id)
    first, second = await make_user(session, "Первый"), await make_user(session, "Второй")
    await session.commit()

    await voting.set_votes(session, round_, first.id, [films[0].id, films[1].id])
    await voting.set_votes(session, round_, second.id, [films[0].id])

    matrix = await voting.build_matrix(session, round_)
    assert matrix.slot_ids == [slot.id]
    assert matrix.cell(films[0].id, slot.id) == 2
    assert matrix.cell(films[1].id, slot.id) == 1
    assert matrix.slot_free == {slot.id: 2}
    assert matrix.voters_without_evening == 0


async def test_fixed_slot_week_is_scheduled_without_a_quorum(session):
    """Особый показ проходит в любом случае: победитель встаёт в свой вечер,
    даже если голосов меньше обычного кворума."""
    from app.services import autopilot

    round_, films, slot, boss = await _special_week(session)
    await rounds_service.publish_shortlist(session, round_, boss.id)
    voter = await make_user(session, "Единственный")
    await session.commit()
    await voting.set_votes(session, round_, voter.id, [films[2].id])

    [assignment] = await autopilot.propose_schedule(session, round_)
    assert (assignment.film_id, assignment.slot_id) == (films[2].id, slot.id)


async def test_special_week_announcement_names_the_theme_and_the_time(session):
    from app.models import Notification
    from app.models.enums import NotificationKind
    from app.services import notify

    round_, _, _, boss = await _special_week(session)
    await make_user(session, "Зритель")
    await session.commit()
    await rounds_service.publish_shortlist(session, round_, boss.id)

    payload = (
        await session.execute(
            sa.select(Notification.payload)
            .where(Notification.kind == NotificationKind.SHORTLIST_PUBLISHED)
            .limit(1)
        )
    ).scalar_one()
    assert payload["theme"] == "🎃 Особый показ на Хэллоуин"
    # Первый вечер недели 7 сентября — понедельник, 19:00 по Москве
    assert payload["fixed_at"] == "понедельник, 7 сентября, 19:00"
    text = notify.render(NotificationKind.SHORTLIST_PUBLISHED, None, "", payload)
    assert "Особый показ на Хэллоуин" in text
    assert "время уже назначено" in text
    assert "вечера" not in text  # выбирать вечера не предлагаем


async def test_only_the_superadmin_previews_the_ballot_before_publishing(session):
    round_, films, _, boss = await _special_week(session)
    assert round_.stage == RoundStage.SHORTLIST_REVIEW

    with pytest.raises(VotingError, match="закрыто"):
        voting.ensure_open(round_)
    voting.ensure_open(round_, preview=True)

    await voting.set_votes(session, round_, boss.id, [films[0].id], preview=True)
    assert await voting.my_votes(session, round_, boss.id) == [films[0].id]


async def test_ballot_preview_is_for_the_superadmin_only(client, session):
    from tests.conftest import SUPERADMIN_TG_ID, login

    boss = await login(client, SUPERADMIN_TG_ID, "Главный")
    viewer = await login(client, 777450, "Зритель")
    round_, _, slot, _ = await _special_week(session)

    seen = await client.get(
        "/api/round/ballot", headers={"Authorization": f"Bearer {boss['token']}"}
    )
    assert seen.status_code == 200
    body = seen.json()
    assert body["preview"] is True and body["fixed_slot"] is True
    assert body["theme_note"] == "🎃 Особый показ на Хэллоуин"
    assert [s["id"] for s in body["slots"]] == [slot.id]

    hidden = await client.get(
        "/api/round/ballot", headers={"Authorization": f"Bearer {viewer['token']}"}
    )
    assert hidden.status_code == 409


def test_namesakes_get_a_year_on_buttons_and_in_the_list():
    from app.models import Film

    films = [
        Film(id=1, title_ru="Семейка Аддамс", year=2019),
        Film(id=2, title_ru="Тайна Коко", year=2017),
        Film(id=3, title_ru="Семейка Аддамс", year=1991),
    ]
    assert voting.labelled(films) == [
        (1, "Семейка Аддамс (2019)"),
        (2, "Тайна Коко"),
        (3, "Семейка Аддамс (1991)"),
    ]


def test_fixed_week_buttons_do_not_ask_for_evenings():
    from app.bot.votes import vote_keyboard

    regular = vote_keyboard(1, [(5, "Фильм")], {5}, "2026-10-26")
    fixed = vote_keyboard(1, [(5, "Фильм")], {5}, "2026-10-26", fixed=True)
    assert len(regular.inline_keyboard) == 2
    assert len(fixed.inline_keyboard) == 1
