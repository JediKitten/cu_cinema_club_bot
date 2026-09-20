"""Турниры: сетка плей-офф на любую тему (расширение по просьбе клуба)."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.models import Notification, Tournament, TournamentMatch, TournamentOption
from app.models.enums import NotificationKind, TournamentStatus, UserRole
from app.services import tournaments
from app.services.tournaments import OptionIn, TournamentError
from tests.conftest import SUPERADMIN_TG_ID, login
from tests.test_weights import make_film, make_user


async def admin(session):
    user = await make_user(session, "Админ")
    user.role = UserRole.ADMIN
    await session.commit()
    return user


def options(count: int) -> list[OptionIn]:
    """Свободные карточки: персонажа в каталоге не найти."""
    return [OptionIn(title=f"Злодей {index}") for index in range(count)]


async def prepared(session, count: int = 4) -> tuple[Tournament, object]:
    boss = await admin(session)
    tournament = await tournaments.create(session, boss.id, "Лучший злодей")
    await tournaments.set_options(session, tournament, options(count))
    return tournament, boss


async def matches_of_round(session, tournament, round_no: int) -> list[TournamentMatch]:
    return list(
        (
            await session.execute(
                sa.select(TournamentMatch)
                .where(
                    TournamentMatch.tournament_id == tournament.id,
                    TournamentMatch.round_no == round_no,
                )
                .order_by(TournamentMatch.position)
            )
        ).scalars()
    )


async def close_current_round(session, tournament) -> None:
    """Сдвигаем срок этапа в прошлое — так же, как это сделает время."""
    for match in await matches_of_round(session, tournament, tournament.current_round):
        match.closes_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()


def test_round_names_read_like_a_bracket():
    assert tournaments.round_name(1) == "финал"
    assert tournaments.round_name(2) == "полуфинал"
    assert tournaments.round_name(4) == "1/4"
    assert tournaments.round_name(8) == "1/8"


async def test_start_requires_a_power_of_two(session):
    """Сетка на шесть вариантов не сходится, а технические поражения лишние."""
    tournament, boss = await prepared(session, count=6)

    with pytest.raises(TournamentError, match="степень двойки"):
        await tournaments.start(session, tournament, boss.id)


async def test_start_pairs_first_seed_with_last(session):
    """Классический посев: сильные по мнению админа встречаются не сразу."""
    tournament, boss = await prepared(session, count=8)
    await tournaments.start(session, tournament, boss.id)

    first_round = await matches_of_round(session, tournament, 1)
    seeds = {
        option.id: option.seed
        for option in (
            await session.execute(
                sa.select(TournamentOption).where(
                    TournamentOption.tournament_id == tournament.id
                )
            )
        ).scalars()
    }

    assert len(first_round) == 4
    assert [
        (seeds[m.option_a_id], seeds[m.option_b_id]) for m in first_round
    ] == [(0, 7), (1, 6), (2, 5), (3, 4)]


async def test_two_tournaments_do_not_run_at_once(session):
    """Два турнира разом — два уведомления в день и разорванное внимание."""
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)

    second = await tournaments.create(session, boss.id, "Лучшая комедия")
    await tournaments.set_options(session, second, options(4))

    with pytest.raises(TournamentError, match="уже идёт"):
        await tournaments.start(session, second, boss.id)


async def test_options_are_frozen_after_the_start(session):
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)

    with pytest.raises(TournamentError, match="до старта"):
        await tournaments.set_options(session, tournament, options(8))


async def test_vote_can_be_changed_until_the_stage_closes(session):
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)
    voter = await make_user(session, "Зритель")
    await session.commit()

    match = (await matches_of_round(session, tournament, 1))[0]
    await tournaments.vote(session, tournament, match.id, voter.id, match.option_a_id)
    await tournaments.vote(session, tournament, match.id, voter.id, match.option_b_id)

    view = await tournaments.view(session, tournament, voter.id)
    voted = view.rounds[0].matches[0]
    assert voted.my_option_id == match.option_b_id
    assert view.left_to_vote == 1  # вторая пара ещё ждёт


async def test_running_stage_hides_the_score(session):
    """Счёт на глазах у голосующих подталкивает к большинству (§11)."""
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)
    voter = await make_user(session, "Зритель")
    await session.commit()

    match = (await matches_of_round(session, tournament, 1))[0]
    await tournaments.vote(session, tournament, match.id, voter.id, match.option_a_id)

    view = await tournaments.view(session, tournament, voter.id)
    live = view.rounds[0].matches[0]
    assert live.votes_a is None and live.votes_b is None
    assert live.my_option_id == match.option_a_id  # свой голос видно всегда


async def test_vote_for_an_option_from_another_pair_is_refused(session):
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)
    voter = await make_user(session, "Зритель")
    await session.commit()

    first, second = await matches_of_round(session, tournament, 1)
    with pytest.raises(TournamentError, match="в этой паре"):
        await tournaments.vote(session, tournament, first.id, voter.id, second.option_a_id)


async def test_stage_closes_by_the_clock_and_opens_the_next(session):
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)
    voter = await make_user(session, "Зритель")
    await session.commit()

    first, second = await matches_of_round(session, tournament, 1)
    await tournaments.vote(session, tournament, first.id, voter.id, first.option_b_id)

    # Пока срок не вышел, тик ничего не трогает.
    assert await tournaments.tick(session) == []

    await close_current_round(session, tournament)
    done = await tournaments.tick(session)
    await session.refresh(tournament)

    assert any("закрыт" in line for line in done)
    assert tournament.current_round == 2
    final = await matches_of_round(session, tournament, 2)
    assert len(final) == 1
    # Проголосованную пару выиграл вариант B, во второй голосов не было —
    # там ничья, и её решает посев.
    assert final[0].option_a_id == first.option_b_id
    assert final[0].option_b_id == second.option_a_id

    # Счёт закрытого этапа виден, и победитель пары тоже.
    view = await tournaments.view(session, tournament, voter.id)
    played = view.rounds[0].matches[0]
    assert played.votes_b == 1
    assert played.winner_option_id == first.option_b_id


async def test_a_tie_is_broken_by_seed(session):
    """Монетка честнее, но необъяснима: посев виден в сетке заранее."""
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)
    one = await make_user(session, "Первый")
    two = await make_user(session, "Второй")
    await session.commit()

    match = (await matches_of_round(session, tournament, 1))[0]
    await tournaments.vote(session, tournament, match.id, one.id, match.option_a_id)
    await tournaments.vote(session, tournament, match.id, two.id, match.option_b_id)

    await close_current_round(session, tournament)
    await tournaments.tick(session)

    await session.refresh(match)
    # option_a — посев 0, option_b — посев 3.
    assert match.winner_option_id == match.option_a_id


async def test_tournament_reaches_a_winner_and_tells_the_club(session):
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)

    await close_current_round(session, tournament)
    await tournaments.tick(session)  # полуфинал → финал
    await close_current_round(session, tournament)
    await tournaments.tick(session)  # финал сыгран

    await session.refresh(tournament)
    assert tournament.status == TournamentStatus.FINISHED
    assert tournament.winner_option_id is not None
    assert tournament.finished_at is not None

    view = await tournaments.view(session, tournament, boss.id)
    assert view.winner is not None
    assert view.rounds[-1].name == "финал"

    kinds = (
        (await session.execute(sa.select(Notification.kind).where(Notification.user_id == boss.id)))
        .scalars()
        .all()
    )
    assert NotificationKind.TOURNAMENT_STARTED in kinds
    assert NotificationKind.TOURNAMENT_FINISHED in kinds


async def test_repeated_tick_does_not_duplicate_the_next_round(session):
    """Фоновые задачи обязаны быть идемпотентными (§17)."""
    tournament, boss = await prepared(session, count=8)
    await tournaments.start(session, tournament, boss.id)
    await close_current_round(session, tournament)

    await tournaments.tick(session)
    await tournaments.tick(session)
    await tournaments.tick(session)

    await session.refresh(tournament)
    assert tournament.current_round == 2
    assert len(await matches_of_round(session, tournament, 2)) == 2


async def test_option_can_point_at_a_film_from_the_catalogue(session):
    """Название и постер берутся из каталога, а не копируются в турнир."""
    boss = await admin(session)
    film = await make_film(session, "Крёстный отец")
    await session.commit()

    tournament = await tournaments.create(session, boss.id, "Лучшая драма")
    await tournaments.set_options(
        session,
        tournament,
        [OptionIn(title="", film_id=film.id), *options(3)],
    )

    view = await tournaments.view(session, tournament, boss.id)
    assert view.options_count == 4

    await tournaments.start(session, tournament, boss.id)
    shown = (await tournaments.view(session, tournament, boss.id)).rounds[0].matches[0]
    assert shown.option_a is not None
    assert shown.option_a.title == "Крёстный отец"
    assert shown.option_a.film_id == film.id


async def test_unknown_film_is_refused(session):
    boss = await admin(session)
    tournament = await tournaments.create(session, boss.id, "Лучшая драма")

    with pytest.raises(TournamentError, match="не найден"):
        await tournaments.set_options(session, tournament, [OptionIn(title="", film_id=999_999)])


async def test_cancelled_tournament_frees_the_slot_for_another(session):
    tournament, boss = await prepared(session, count=4)
    await tournaments.start(session, tournament, boss.id)
    await tournaments.cancel(session, tournament, boss.id)

    second = await tournaments.create(session, boss.id, "Лучшая комедия")
    await tournaments.set_options(session, second, options(4))
    await tournaments.start(session, second, boss.id)

    assert (await tournaments.active(session)).id == second.id


# --- HTTP -------------------------------------------------------------------


async def test_admin_creates_and_starts_a_tournament_over_http(client, session):
    auth = await login(client, SUPERADMIN_TG_ID, "Главный")
    boss = {"Authorization": f"Bearer {auth['token']}"}

    created = await client.post(
        "/api/tournaments",
        json={"title": "Лучший злодей", "description": "Выбираем всем клубом"},
        headers=boss,
    )
    assert created.status_code == 200, created.text
    tournament_id = created.json()["id"]

    filled = await client.put(
        f"/api/tournaments/{tournament_id}/options",
        json={"options": [{"title": f"Злодей {i}"} for i in range(4)]},
        headers=boss,
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["options_count"] == 4

    started = await client.post(f"/api/tournaments/{tournament_id}/start", headers=boss)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "running"
    assert body["rounds"][0]["name"] == "полуфинал"
    assert body["left_to_vote"] == 2


async def test_participant_votes_but_cannot_start_a_tournament(client, session):
    auth = await login(client, SUPERADMIN_TG_ID, "Главный")
    boss = {"Authorization": f"Bearer {auth['token']}"}
    created = await client.post(
        "/api/tournaments", json={"title": "Лучшая комедия"}, headers=boss
    )
    tournament_id = created.json()["id"]
    await client.put(
        f"/api/tournaments/{tournament_id}/options",
        json={"options": [{"title": f"Комедия {i}"} for i in range(4)]},
        headers=boss,
    )
    await client.post(f"/api/tournaments/{tournament_id}/start", headers=boss)

    guest = await login(client, 555001, "Зритель")
    viewer = {"Authorization": f"Bearer {guest['token']}"}
    refused = await client.post(f"/api/tournaments/{tournament_id}/start", headers=viewer)
    assert refused.status_code == 403

    current = await client.get("/api/tournaments/current", headers=viewer)
    assert current.status_code == 200
    match = current.json()["rounds"][0]["matches"][0]

    voted = await client.post(
        f"/api/tournaments/{tournament_id}/vote",
        json={"match_id": match["id"], "option_id": match["option_a"]["id"]},
        headers=viewer,
    )
    assert voted.status_code == 200, voted.text
    assert voted.json()["rounds"][0]["matches"][0]["my_option_id"] == match["option_a"]["id"]
    assert voted.json()["left_to_vote"] == 1


async def test_no_tournament_means_no_banner(client, session):
    guest = await login(client, 555002, "Зритель")
    empty = await client.get(
        "/api/tournaments/current",
        headers={"Authorization": f"Bearer {guest['token']}"},
    )

    assert empty.status_code == 200
    assert empty.json() is None
