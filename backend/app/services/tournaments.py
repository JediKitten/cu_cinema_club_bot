"""Турниры: сетка плей-офф на любую тему (расширение по просьбе клуба).

Админ заводит тему и варианты, клуб голосует парами. Каждый этап длится
сутки, дальше проходит победитель. Вариантов должно быть степень двойки —
иначе сетка не сходится, а «технические поражения» в развлечении лишние.

Промежуточный счёт пары до закрытия этапа не показывается. Причина та же,
по которой каталог не сортируется по популярности (§11): увидев, что один
вариант ведёт, человек голосует за него, а не за то, что ему нравится.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Film,
    Tournament,
    TournamentMatch,
    TournamentOption,
    TournamentVote,
    User,
)
from app.models.enums import NotificationKind, TournamentStatus
from app.services import notify
from app.services.settings import SettingsService
from app.services.tmdb import poster_url

logger = logging.getLogger(__name__)

# Меньше четырёх — это не сетка, а одна пара; больше тридцати двух никто
# не досмотрит: тридцать два варианта это уже пять дней голосования.
MIN_OPTIONS = 4
MAX_OPTIONS = 32


class TournamentError(ValueError):
    """Причину показываем как есть."""


def round_name(matches_in_round: int) -> str:
    """Как называется этап, в котором столько пар."""
    match matches_in_round:
        case 1:
            return "финал"
        case 2:
            return "полуфинал"
        case _:
            return f"1/{matches_in_round}"


def is_power_of_two(value: int) -> bool:
    return value >= 2 and value & (value - 1) == 0


@dataclass(slots=True)
class OptionIn:
    """Вариант, каким его задаёт админ."""

    title: str
    subtitle: str | None = None
    image_url: str | None = None
    film_id: int | None = None


@dataclass(slots=True)
class OptionView:
    id: int
    seed: int
    title: str
    subtitle: str | None
    image_url: str | None
    film_id: int | None


@dataclass(slots=True)
class MatchView:
    id: int
    round_no: int
    position: int
    option_a: OptionView | None
    option_b: OptionView | None
    opens_at: datetime
    closes_at: datetime
    # Мой голос — единственное, что видно, пока этап идёт.
    my_option_id: int | None = None
    # Счёт и победитель появляются только после закрытия этапа.
    votes_a: int | None = None
    votes_b: int | None = None
    winner_option_id: int | None = None


@dataclass(slots=True)
class RoundView:
    round_no: int
    name: str
    closed: bool
    matches: list[MatchView] = field(default_factory=list)


@dataclass(slots=True)
class TournamentView:
    id: int
    title: str
    description: str | None
    status: str
    current_round: int
    stage_hours: int
    options_count: int
    started_at: datetime | None
    finished_at: datetime | None
    winner: OptionView | None = None
    rounds: list[RoundView] = field(default_factory=list)
    # Сколько пар текущего этапа человек ещё не отголосовал.
    left_to_vote: int = 0
    closes_at: datetime | None = None


# --- Чтение ----------------------------------------------------------------


async def _options(session: AsyncSession, tournament_id: int) -> dict[int, OptionView]:
    """Варианты турнира. У привязанных к каталогу название и постер — оттуда.

    Иначе карточка в сетке устаревала бы: фильм переименовали или постер
    сменился, а в турнире по-прежнему старое.
    """
    rows = (
        await session.execute(
            sa.select(TournamentOption, Film)
            .outerjoin(Film, Film.id == TournamentOption.film_id)
            .where(TournamentOption.tournament_id == tournament_id)
            .order_by(TournamentOption.seed)
        )
    ).all()
    return {
        option.id: OptionView(
            id=option.id,
            seed=option.seed,
            title=film.title_ru if film else option.title,
            subtitle=(str(film.year) if film and film.year else option.subtitle),
            image_url=poster_url(film.poster_path) if film else option.image_url,
            film_id=option.film_id,
        )
        for option, film in rows
    }


async def _vote_counts(session: AsyncSession, match_ids: list[int]) -> dict[tuple[int, int], int]:
    """Сколько голосов у каждого варианта в каждой паре."""
    if not match_ids:
        return {}
    rows = await session.execute(
        sa.select(TournamentVote.match_id, TournamentVote.option_id, sa.func.count())
        .where(TournamentVote.match_id.in_(match_ids))
        .group_by(TournamentVote.match_id, TournamentVote.option_id)
    )
    return {(match_id, option_id): count for match_id, option_id, count in rows}


async def view(
    session: AsyncSession, tournament: Tournament, viewer_id: int | None
) -> TournamentView:
    options = await _options(session, tournament.id)
    matches = (
        (
            await session.execute(
                sa.select(TournamentMatch)
                .where(TournamentMatch.tournament_id == tournament.id)
                .order_by(TournamentMatch.round_no, TournamentMatch.position)
            )
        )
        .scalars()
        .all()
    )

    mine: dict[int, int] = {}
    if viewer_id is not None and matches:
        mine = {
            match_id: option_id
            for match_id, option_id in await session.execute(
                sa.select(TournamentVote.match_id, TournamentVote.option_id).where(
                    TournamentVote.user_id == viewer_id,
                    TournamentVote.match_id.in_([m.id for m in matches]),
                )
            )
        }

    # Счёт нужен только по закрытым этапам — по идущему его не показываем.
    closed_ids = [m.id for m in matches if m.round_no < tournament.current_round]
    counts = await _vote_counts(session, closed_ids)

    rounds: dict[int, RoundView] = {}
    left_to_vote = 0
    closes_at = None
    for match in matches:
        closed = match.round_no < tournament.current_round
        bucket = rounds.setdefault(
            match.round_no, RoundView(round_no=match.round_no, name="", closed=closed)
        )
        bucket.matches.append(
            MatchView(
                id=match.id,
                round_no=match.round_no,
                position=match.position,
                option_a=options.get(match.option_a_id) if match.option_a_id else None,
                option_b=options.get(match.option_b_id) if match.option_b_id else None,
                opens_at=match.opens_at,
                closes_at=match.closes_at,
                my_option_id=mine.get(match.id),
                votes_a=counts.get((match.id, match.option_a_id), 0) if closed else None,
                votes_b=counts.get((match.id, match.option_b_id), 0) if closed else None,
                winner_option_id=match.winner_option_id,
            )
        )
        if match.round_no == tournament.current_round:
            closes_at = match.closes_at
            if match.id not in mine:
                left_to_vote += 1

    for bucket in rounds.values():
        bucket.name = round_name(len(bucket.matches))

    return TournamentView(
        id=tournament.id,
        title=tournament.title,
        description=tournament.description,
        status=tournament.status,
        current_round=tournament.current_round,
        stage_hours=tournament.stage_hours,
        options_count=len(options),
        started_at=tournament.started_at,
        finished_at=tournament.finished_at,
        winner=options.get(tournament.winner_option_id) if tournament.winner_option_id else None,
        rounds=[rounds[key] for key in sorted(rounds)],
        left_to_vote=left_to_vote,
        closes_at=closes_at,
    )


async def active(session: AsyncSession) -> Tournament | None:
    """Идущий турнир. Больше одного разом не запускаем — см. `start`."""
    return (
        await session.execute(
            sa.select(Tournament).where(Tournament.status == TournamentStatus.RUNNING).limit(1)
        )
    ).scalar_one_or_none()


async def listing(session: AsyncSession, statuses: list[str] | None = None) -> list[Tournament]:
    query = sa.select(Tournament).order_by(Tournament.created_at.desc())
    if statuses:
        query = query.where(Tournament.status.in_(statuses))
    return list((await session.execute(query)).scalars())


# --- Правка ----------------------------------------------------------------


async def create(
    session: AsyncSession, actor_id: int, title: str, description: str | None = None
) -> Tournament:
    if not title.strip():
        raise TournamentError("У турнира должна быть тема")
    tournament = Tournament(
        title=title.strip(), description=(description or "").strip() or None, created_by=actor_id
    )
    session.add(tournament)
    await session.flush()
    session.add(
        AuditLog(
            actor_id=actor_id, entity="tournament", entity_id=tournament.id, action="create"
        )
    )
    await session.commit()
    return tournament


async def set_options(
    session: AsyncSession, tournament: Tournament, options: list[OptionIn]
) -> list[TournamentOption]:
    """Заменяет список вариантов целиком. Только у черновика.

    Порядок, в котором их прислали, — это и есть посев: первый встречается
    с последним, второй с предпоследним, как в обычной сетке.
    """
    if tournament.status != TournamentStatus.DRAFT:
        raise TournamentError("Варианты правятся только до старта")
    if len(options) > MAX_OPTIONS:
        raise TournamentError(f"Больше {MAX_OPTIONS} вариантов не поместится в сетку")

    for option in options:
        if not option.title.strip() and option.film_id is None:
            raise TournamentError("У варианта должно быть название или фильм")

    known_films = set(
        (
            await session.execute(
                sa.select(Film.id).where(
                    Film.id.in_([o.film_id for o in options if o.film_id is not None])
                )
            )
        )
        .scalars()
        .all()
    )
    for option in options:
        if option.film_id is not None and option.film_id not in known_films:
            raise TournamentError("Фильм не найден в каталоге")

    await session.execute(
        sa.delete(TournamentOption).where(TournamentOption.tournament_id == tournament.id)
    )
    # Сброс до вставки: иначе уникальность (турнир, посев) ломается при
    # перестановке уже заведённых вариантов.
    await session.flush()
    session.add_all(
        TournamentOption(
            tournament_id=tournament.id,
            seed=seed,
            title=option.title.strip() or "Без названия",
            subtitle=(option.subtitle or "").strip() or None,
            image_url=(option.image_url or "").strip() or None,
            film_id=option.film_id,
        )
        for seed, option in enumerate(options)
    )
    await session.commit()
    return list(
        (
            await session.execute(
                sa.select(TournamentOption)
                .where(TournamentOption.tournament_id == tournament.id)
                .order_by(TournamentOption.seed)
            )
        ).scalars()
    )


async def start(session: AsyncSession, tournament: Tournament, actor_id: int) -> Tournament:
    """Открывает первый этап и зовёт клуб голосовать."""
    if tournament.status != TournamentStatus.DRAFT:
        raise TournamentError("Турнир уже запускали")
    if await active(session) is not None:
        raise TournamentError("Один турнир уже идёт — дождитесь его конца или отмените")

    options = list(
        (
            await session.execute(
                sa.select(TournamentOption)
                .where(TournamentOption.tournament_id == tournament.id)
                .order_by(TournamentOption.seed)
            )
        ).scalars()
    )
    if len(options) < MIN_OPTIONS or not is_power_of_two(len(options)):
        raise TournamentError(
            f"Вариантов должно быть степень двойки — {MIN_OPTIONS}, 8, 16 или {MAX_OPTIONS}. "
            f"Сейчас {len(options)}."
        )

    tournament.stage_hours = int(await SettingsService(session).get("tournament_stage_hours"))
    tournament.status = TournamentStatus.RUNNING
    tournament.current_round = 1
    tournament.started_at = datetime.now(UTC)

    # Классический посев: первый с последним, второй с предпоследним. Так
    # сильные по мнению админа варианты встречаются не в первом же круге.
    opens_at = datetime.now(UTC)
    closes_at = opens_at + timedelta(hours=tournament.stage_hours)
    for position in range(len(options) // 2):
        session.add(
            TournamentMatch(
                tournament_id=tournament.id,
                round_no=1,
                position=position,
                option_a_id=options[position].id,
                option_b_id=options[-1 - position].id,
                opens_at=opens_at,
                closes_at=closes_at,
            )
        )

    session.add(
        AuditLog(actor_id=actor_id, entity="tournament", entity_id=tournament.id, action="start")
    )
    await _announce(
        session,
        tournament,
        NotificationKind.TOURNAMENT_STARTED,
        key=f"tournament:{tournament.id}:start",
        payload={
            "title": tournament.title,
            "round": round_name(len(options) // 2),
            "tournament_id": tournament.id,
        },
    )
    await session.commit()
    return tournament


async def cancel(session: AsyncSession, tournament: Tournament, actor_id: int) -> Tournament:
    if tournament.status == TournamentStatus.FINISHED:
        raise TournamentError("Завершённый турнир не отменить")
    tournament.status = TournamentStatus.CANCELLED
    session.add(
        AuditLog(actor_id=actor_id, entity="tournament", entity_id=tournament.id, action="cancel")
    )
    await session.commit()
    return tournament


async def vote(
    session: AsyncSession, tournament: Tournament, match_id: int, user_id: int, option_id: int
) -> None:
    """Голос за вариант в паре. Передумать можно, пока этап не закрылся."""
    if tournament.status != TournamentStatus.RUNNING:
        raise TournamentError("Турнир не идёт")

    match = await session.get(TournamentMatch, match_id)
    if match is None or match.tournament_id != tournament.id:
        raise TournamentError("Пара не найдена")
    if match.round_no != tournament.current_round:
        raise TournamentError("Этот этап уже закрыт")
    if datetime.now(UTC) >= match.closes_at:
        raise TournamentError("Голосование этого этапа закончилось")
    if option_id not in (match.option_a_id, match.option_b_id):
        raise TournamentError("Такого варианта в этой паре нет")

    await session.execute(
        insert(TournamentVote)
        .values(match_id=match_id, user_id=user_id, option_id=option_id)
        # Передумать можно: голос заменяется, а не добавляется вторым.
        .on_conflict_do_update(
            index_elements=[TournamentVote.match_id, TournamentVote.user_id],
            set_={"option_id": option_id},
        )
    )
    await session.commit()


# --- Продвижение по времени ------------------------------------------------


async def tick(session: AsyncSession) -> list[str]:
    """Закрывает созревшие этапы и открывает следующие. Идемпотентна.

    Вызывается из того же фонового цикла, что и `cycle.tick`.
    """
    done: list[str] = []
    tournament = await active(session)
    if tournament is None:
        return done

    # Блокировка строки турнира: два прохода разом (перезапуск с наложением,
    # ручной вызов) иначе создали бы следующий этап дважды.
    tournament = (
        await session.execute(
            sa.select(Tournament).where(Tournament.id == tournament.id).with_for_update()
        )
    ).scalar_one()

    matches = list(
        (
            await session.execute(
                sa.select(TournamentMatch)
                .where(
                    TournamentMatch.tournament_id == tournament.id,
                    TournamentMatch.round_no == tournament.current_round,
                )
                .order_by(TournamentMatch.position)
            )
        ).scalars()
    )
    if not matches or datetime.now(UTC) < matches[0].closes_at:
        return done

    counts = await _vote_counts(session, [m.id for m in matches])
    options = await _options(session, tournament.id)
    winners: list[int] = []
    for match in matches:
        winner = _winner(match, counts, options)
        match.winner_option_id = winner
        winners.append(winner)
    done.append(f"этап {tournament.current_round} закрыт")

    if len(winners) == 1:
        tournament.status = TournamentStatus.FINISHED
        tournament.finished_at = datetime.now(UTC)
        tournament.winner_option_id = winners[0]
        tournament.current_round += 1
        await _announce(
            session,
            tournament,
            NotificationKind.TOURNAMENT_FINISHED,
            key=f"tournament:{tournament.id}:finish",
            payload={
                "title": tournament.title,
                "winner": options[winners[0]].title,
                "tournament_id": tournament.id,
            },
        )
        done.append(f"победил «{options[winners[0]].title}»")
    else:
        tournament.current_round += 1
        opens_at = datetime.now(UTC)
        closes_at = opens_at + timedelta(hours=tournament.stage_hours)
        for position in range(len(winners) // 2):
            session.add(
                TournamentMatch(
                    tournament_id=tournament.id,
                    round_no=tournament.current_round,
                    position=position,
                    option_a_id=winners[position * 2],
                    option_b_id=winners[position * 2 + 1],
                    opens_at=opens_at,
                    closes_at=closes_at,
                )
            )
        name = round_name(len(winners) // 2)
        await _announce(
            session,
            tournament,
            NotificationKind.TOURNAMENT_ROUND_OPENED,
            key=f"tournament:{tournament.id}:round:{tournament.current_round}",
            payload={
                "title": tournament.title,
                "round": name,
                "tournament_id": tournament.id,
            },
        )
        done.append(f"открыт {name}")

    await session.commit()
    logger.info("Турнир %s: %s", tournament.id, "; ".join(done))
    return done


def _winner(
    match: TournamentMatch, counts: dict[tuple[int, int], int], options: dict[int, OptionView]
) -> int:
    """Кто прошёл дальше.

    Ничья решается посевом: проходит тот, кого админ поставил выше. Монетка
    была бы честнее, но необъяснима — а посев виден в сетке заранее.
    """
    a, b = match.option_a_id, match.option_b_id
    if a is None:
        return b
    if b is None:
        return a
    votes_a = counts.get((match.id, a), 0)
    votes_b = counts.get((match.id, b), 0)
    if votes_a != votes_b:
        return a if votes_a > votes_b else b
    return a if options[a].seed < options[b].seed else b


async def _announce(
    session: AsyncSession,
    tournament: Tournament,
    kind: NotificationKind,
    key: str,
    payload: dict,
) -> None:
    """Зовём весь клуб: турнир — развлечение для всех, а не для голосовавших."""
    audience = (
        (await session.execute(sa.select(User.id).where(User.is_active, User.tg_id.is_not(None))))
        .scalars()
        .all()
    )
    for user_id in audience:
        await notify.queue(session, user_id, kind, dedup_key=f"{key}:{user_id}", payload=payload)
