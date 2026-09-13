"""Ачивки: бейджи за участие в клубе (расширение по просьбе клуба).

Устроены ступенями. У каждой цели — «сколько фильмов посмотрел», «сколько
сеансов посетил» — четыре уровня: бронза, серебро, золото, платина. Человек
держит только **высшую достигнутую**: заработал серебро — бронза той же цели
заменяется, а не копится рядом. Поэтому в профиле четыре числа, а не список
из двадцати строк.

Правила живут реестром в коде, а не в базе — как и параметры §13. Добавить
ступень значит дописать строку: ни миграции, ни правки схемы. В базе лежит
только факт выдачи, чтобы поздравить ровно один раз.

Секретные ачивки до получения не показываются вовсе — ни названия, ни условия,
только счётчик «осталось столько-то». В этом и смысл: найти их должно быть
сюрпризом.

Считаем не по одному человеку, а всех сразу: показателей семь, и семь
группировок раз в пять минут дешевле, чем семь запросов на каждого участника.
"""

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Achievement,
    Attendance,
    AuditLog,
    Favourite,
    Film,
    FilmRating,
    FilmSkip,
    Friendship,
    Interest,
    Referral,
    Screening,
    Tournament,
    TournamentMatch,
    TournamentVote,
    User,
    Watch,
)
from app.models.enums import FilmStatus, NotificationKind, TournamentStatus
from app.services import notify

logger = logging.getLogger(__name__)


class Tier(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


# Порядок важен: по нему решается, какая ступень выше и что кого заменяет.
TIERS: tuple[Tier, ...] = (Tier.BRONZE, Tier.SILVER, Tier.GOLD, Tier.PLATINUM)

TIER_EMOJI: dict[Tier, str] = {
    Tier.BRONZE: "🥉",
    Tier.SILVER: "🥈",
    Tier.GOLD: "🥇",
    Tier.PLATINUM: "🏆",
}

# Ниже этого размера каталога «конец ленты» ничего не значит: свежая установка
# и демо-данные пролистываются за минуту.
DECK_MIN_CATALOGUE = 100

TIER_LABEL: dict[Tier, str] = {
    Tier.BRONZE: "бронзовая",
    Tier.SILVER: "серебряная",
    Tier.GOLD: "золотая",
    Tier.PLATINUM: "платиновая",
}


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    # Цель. Ачивки одной цели вытесняют друг друга: остаётся высшая.
    group: str
    tier: Tier
    title: str
    description: str
    metric: str
    target: int
    # Секретную не видно, пока не получена: ни названия, ни условия.
    secret: bool = False

    @property
    def rank(self) -> int:
        return TIERS.index(self.tier)


# Порядок — как в таблице клуба: она и есть источник правды, а в профиле цели
# идут теми же строками, что там.
GROUP_LABEL: dict[str, str] = {
    "films": "Просмотренные фильмы",
    "screenings": "Сеансы клуба",
    "english": "Сеансы на английском",
    "friends": "Друзья",
    "ratings": "Оценки",
    "referrals": "Приглашённые на фильм",
}

RULES: tuple[Rule, ...] = (
    # --- Кол-во фильмов ---
    Rule(
        "films_bronze", "films", Tier.BRONZE,
        "Да, я что-то там смотрел...", "Посмотреть 5 фильмов", "watched", 5,
    ),
    Rule(
        "films_silver", "films", Tier.SILVER, "Люблю кино", "Посмотреть 50 фильмов", "watched", 50
    ),
    Rule("films_gold", "films", Tier.GOLD, "Киноман", "Посмотреть 200 фильмов", "watched", 200),
    Rule(
        "films_platinum", "films", Tier.PLATINUM,
        "Я есть Тарантино", "Посмотреть 1000 фильмов", "watched", 1000,
    ),
    # --- Кол-во сеансов ---
    Rule(
        "screenings_bronze", "screenings", Tier.BRONZE,
        "Узнал о киноклубе", "Посетить 1 сеанс", "attended", 1,
    ),
    Rule(
        "screenings_silver", "screenings", Tier.SILVER,
        "Хожу в киноклуб", "Посетить 5 сеансов", "attended", 5,
    ),
    Rule(
        "screenings_gold", "screenings", Tier.GOLD,
        "Люблю киноклуб", "Посетить 15 сеансов", "attended", 15,
    ),
    Rule(
        "screenings_platinum", "screenings", Tier.PLATINUM,
        "Я есть киноклуб", "Посетить 50 сеансов", "attended", 50,
    ),
    # --- Кол-во сеансов на английском ---
    Rule(
        "english_bronze", "english", Tier.BRONZE,
        "Hello world", "Посмотреть 1 фильм на английском", "english", 1,
    ),
    Rule(
        "english_silver", "english", Tier.SILVER,
        "Ландон из зе кэпитал оф Грейт бритен",
        "Посмотреть 5 фильмов на английском", "english", 5,
    ),
    Rule(
        "english_gold", "english", Tier.GOLD,
        "C3 english level", "Посмотреть 10 фильмов на английском", "english", 10,
    ),
    Rule(
        "english_platinum", "english", Tier.PLATINUM,
        "English mf, do you speak it?", "Посмотреть 25 фильмов на английском", "english", 25,
    ),
    # --- Кол-во друзей ---
    Rule(
        "friends_bronze", "friends", Tier.BRONZE,
        "Are you lonely? I can fix that", "Добавить в друзья 1 человека", "friends", 1,
    ),
    Rule(
        "friends_silver", "friends", Tier.SILVER,
        "Бешеные псы", "Добавить в друзья 5 человек", "friends", 5,
    ),
    Rule(
        "friends_gold", "friends", Tier.GOLD,
        "Друзья Оушена", "Добавить в друзья 10 человек", "friends", 10,
    ),
    Rule(
        "friends_platinum", "friends", Tier.PLATINUM,
        "Я есть экстраверт", "Добавить в друзья 50 человек", "friends", 50,
    ),
    # --- Кол-во оценок ---
    Rule(
        "ratings_bronze", "ratings", Tier.BRONZE,
        "Появилось свое мнение...", "Оценить 5 фильмов", "ratings", 5,
    ),
    Rule(
        "ratings_silver", "ratings", Tier.SILVER,
        "Готов высказаться", "Оценить 25 фильмов", "ratings", 25,
    ),
    Rule(
        "ratings_gold", "ratings", Tier.GOLD,
        "Uhm, actually...", "Поставить 100 оценок", "ratings", 100,
    ),
    Rule(
        "ratings_platinum", "ratings", Tier.PLATINUM,
        "Я есть киноакадемия", "Поставить 500 оценок", "ratings", 500,
    ),
    # --- Кол-во рефералов. Бронзы у этой цели в таблице нет: ступень начинается
    #     сразу с серебра, и лесенка это допускает.
    Rule(
        "referrals_silver", "referrals", Tier.SILVER,
        # Названия для этой ступени в таблице не было — оно наше и правится
        # одной строкой, как и всё здесь.
        "Первое правило киноклуба", "Позвать на фильм 10 человек", "referrals", 10,
    ),
    Rule(
        "referrals_gold", "referrals", Tier.GOLD,
        "Революционер", "Позвать на фильм в сумме 50 человек", "referrals", 50,
    ),
    Rule(
        "referrals_platinum", "referrals", Tier.PLATINUM,
        "Нас 25 тысяч, и мы идем смотреть кино",
        "Позвать на фильм в сумме 200 человек", "referrals", 200,
    ),
    # --- Секретные ---
    Rule(
        "showcase_silver", "showcase", Tier.SILVER,
        "Choose your fighter", "Выбрать 4 любимых фильма в профиле", "favourites", 4, secret=True,
    ),
    Rule(
        "champion_gold", "champion", Tier.GOLD,
        "Абсолютный чемпион",
        "Сделать все выборы в турнире в пользу победителя",
        "champion", 1, secret=True,
    ),
    Rule(
        "deck_platinum", "deck", Tier.PLATINUM,
        "Пойди, пожалуйста, потрогай траву", "Долистать до конца ленты", "deck", 1, secret=True,
    ),
)

BY_CODE = {rule.code: rule for rule in RULES}

# Код именной ачивки. Префикс нужен, чтобы она никогда не столкнулась с кодом
# из реестра и чтобы одного взгляда на строку хватало понять, откуда она.
CUSTOM_PREFIX = "custom:"

# Ступени одной цели, от низшей к высшей.
LADDERS: dict[str, tuple[Rule, ...]] = {
    group: tuple(sorted((r for r in RULES if r.group == group), key=lambda r: r.rank))
    for group in dict.fromkeys(rule.group for rule in RULES)
}


@dataclass(slots=True)
class Step:
    """Одна ступень цели — строка во вкладке своей редкости."""

    tier: Tier
    title: str
    description: str
    target: int
    progress: int
    earned_at: datetime | None = None

    @property
    def done(self) -> bool:
        return self.earned_at is not None


@dataclass(slots=True)
class GroupState:
    """Одна цель: что уже получено, сколько до следующей ступени и вся лестница.

    Лестница нужна целиком: вкладка уровня показывает все ступени этого
    уровня, а не только достижимую следующую — иначе «золото» у новичка
    выглядит пустым, хотя там есть на что посмотреть.
    """

    group: str
    label: str
    secret: bool
    # Придумана админом под конкретного человека, а не взята из реестра.
    custom: bool = False
    # Секретная, которую смотрящий сам ещё не открыл: трофей видно, название
    # и условие — нет.
    hidden: bool = False
    # Полученное — высшая достигнутая ступень. None, если ещё ничего.
    tier: Tier | None = None
    emoji: str = ""
    title: str = ""
    description: str = ""
    earned_at: datetime | None = None
    # Куда расти. None, если взята платина.
    next_title: str | None = None
    next_description: str | None = None
    next_tier: Tier | None = None
    progress: int = 0
    target: int = 0
    steps: list[Step] = field(default_factory=list)


@dataclass(slots=True)
class Summary:
    """Четыре числа для профиля — по одному на уровень."""

    bronze: int = 0
    silver: int = 0
    gold: int = 0
    platinum: int = 0
    # Сколько секретных ещё не найдено, по уровням: у каждой вкладки свой
    # счётчик. Названия и условия не раскрываем — только то, что она есть.
    secrets_left: dict[str, int] = field(default_factory=dict)
    groups: list[GroupState] | None = None


def _counts(model, column: str = "user_id"):
    return sa.select(getattr(model, column), sa.func.count()).group_by(getattr(model, column))


async def _champions(session: AsyncSession) -> set[int]:
    """Кто прошёл турнир, ни разу не ошибившись.

    «Все выборы в пользу победителя» — это и полное участие тоже: проголосовать
    в одной паре и угадать не считается подвигом.
    """
    # Отдельный псевдоним и явная корреляция: во внешнем запросе TournamentMatch
    # уже участвует, и без этого SQLAlchemy склеит их в один и останется без FROM.
    every_match = sa.orm.aliased(TournamentMatch)
    total = (
        sa.select(sa.func.count())
        .select_from(every_match)
        .where(every_match.tournament_id == Tournament.id)
        .correlate(Tournament)
        .scalar_subquery()
    )
    rows = await session.execute(
        sa.select(TournamentVote.user_id)
        .join(TournamentMatch, TournamentMatch.id == TournamentVote.match_id)
        .join(Tournament, Tournament.id == TournamentMatch.tournament_id)
        .where(Tournament.status == TournamentStatus.FINISHED)
        .group_by(TournamentVote.user_id, Tournament.id)
        .having(sa.func.count() == total)
        .having(
            sa.func.count()
            == sa.func.count().filter(TournamentVote.option_id == TournamentMatch.winner_option_id)
        )
    )
    return set(rows.scalars())


async def _finished_the_deck(session: AsyncSession) -> set[int]:
    """Кто не оставил в ленте ни одной неразмеченной карточки.

    «Высказался» считается так же, как в самой ленте (`deck._spoken_for`):
    отметил, оценил, посмотрел или пролистнул.
    """
    total = await session.scalar(
        sa.select(sa.func.count()).select_from(Film).where(Film.status == FilmStatus.ACTIVE)
    )
    if not total or total < DECK_MIN_CATALOGUE:
        # Долистать пустой каталог или два десятка демо-фильмов — не подвиг,
        # а свойство базы. Платина за это обесценила бы её у всех остальных.
        return set()

    spoken = sa.union(
        sa.select(Interest.user_id, Interest.film_id).where(Interest.revoked_at.is_(None)),
        sa.select(FilmRating.user_id, FilmRating.film_id),
        sa.select(Watch.user_id, Watch.film_id),
        sa.select(FilmSkip.user_id, FilmSkip.film_id),
    ).subquery("spoken")

    rows = await session.execute(
        sa.select(spoken.c.user_id)
        .join(Film, Film.id == spoken.c.film_id)
        .where(Film.status == FilmStatus.ACTIVE)
        .group_by(spoken.c.user_id)
        .having(sa.func.count(sa.distinct(spoken.c.film_id)) >= total)
    )
    return set(rows.scalars())


async def metrics(
    session: AsyncSession, user_ids: list[int] | None = None
) -> dict[int, dict[str, int]]:
    """Показатели по всем участникам разом: {user_id: {метрика: число}}."""
    queries = {
        "watched": _counts(Watch),
        "attended": _counts(Attendance),
        "ratings": _counts(FilmRating),
        # «Добавить в друзья» — это подписка, и считается она по исходящим:
        # взаимность зависит от другого человека, а ачивка — про твои действия.
        "friends": _counts(Friendship),
        "favourites": _counts(Favourite),
        # Показ на английском — свойство сеанса: один фильм клуб может показать
        # и с дубляжом, и в оригинале, и считается именно приход в зал.
        "english": (
            sa.select(Attendance.user_id, sa.func.count())
            .join(Screening, Screening.id == Attendance.screening_id)
            .where(Screening.in_english)
            .group_by(Attendance.user_id)
        ),
        # Позвал на фильм — это не переход по ссылке, а согласие: приглашённый
        # отметил фильм уже после перехода. Тот же расчёт, что в referrals.stats.
        "referrals": (
            sa.select(Referral.referrer_id, sa.func.count())
            .join(
                Interest,
                sa.and_(
                    Interest.user_id == Referral.invitee_id,
                    Interest.film_id == Referral.film_id,
                    Interest.revoked_at.is_(None),
                    Interest.created_at >= Referral.created_at,
                ),
            )
            .group_by(Referral.referrer_id)
        ),
    }

    result: dict[int, dict[str, int]] = {}
    for metric, query in queries.items():
        if user_ids is not None:
            column = list(query.selected_columns)[0]
            query = query.where(column.in_(user_ids))
        for user_id, count in await session.execute(query):
            result.setdefault(user_id, {})[metric] = count

    for user_id in await _champions(session):
        if user_ids is None or user_id in user_ids:
            result.setdefault(user_id, {})["champion"] = 1
    for user_id in await _finished_the_deck(session):
        if user_ids is None or user_id in user_ids:
            result.setdefault(user_id, {})["deck"] = 1

    return result


# Чем подменяем секретную в чужом профиле.
HIDDEN_TITLE = "Секретное достижение"
HIDDEN_HINT = "Что это — не скажем: найдите сами"


async def of_user(
    session: AsyncSession, user_id: int, viewer_id: int | None = None
) -> Summary:
    """Что человек собрал и куда ему расти.

    `viewer_id` — тот, кто смотрит. Секретную, которую он сам ещё не открыл,
    в чужом профиле видно только как трофей: название и условие скрыты, иначе
    достаточно было бы заглянуть к любому старожилу, чтобы узнать их все.
    """
    counts = (await metrics(session, [user_id])).get(user_id, {})
    earned = {
        code: at
        for code, at in await session.execute(
            sa.select(Achievement.code, Achievement.earned_at).where(
                Achievement.user_id == user_id
            )
        )
    }

    # Что смотрящий открыл сам. В своём профиле скрывать нечего.
    seen: set[str] = set()
    if viewer_id is not None and viewer_id != user_id:
        seen = set(
            (
                await session.execute(
                    sa.select(Achievement.code).where(Achievement.user_id == viewer_id)
                )
            )
            .scalars()
            .all()
        )
    else:
        seen = set(earned)

    summary = Summary(groups=[])

    # Именные — первыми: их получают штучно и за что-то настоящее, и теряться
    # среди двух десятков ступеней им незачем.
    for row in (
        await session.execute(
            sa.select(Achievement)
            .where(Achievement.user_id == user_id, Achievement.title.is_not(None))
            .order_by(Achievement.earned_at)
        )
    ).scalars():
        tier = Tier(row.tier) if row.tier in set(Tier) else Tier.GOLD
        summary.groups.append(
            GroupState(
                group=row.code,
                label=row.title or "Именная ачивка",
                secret=False,
                custom=True,
                tier=tier,
                emoji=TIER_EMOJI[tier],
                title=row.title or "Именная ачивка",
                description=row.description or "",
                earned_at=row.earned_at,
                steps=[
                    Step(
                        tier=tier,
                        title=row.title or "Именная ачивка",
                        description=row.description or "",
                        target=1,
                        progress=1,
                        earned_at=row.earned_at,
                    )
                ],
            )
        )
        setattr(summary, tier.value, getattr(summary, tier.value) + 1)

    for group, ladder in LADDERS.items():
        secret = ladder[0].secret
        done = [rule for rule in ladder if rule.code in earned]
        top = done[-1] if done else None
        nxt = next((rule for rule in ladder if rule.code not in earned), None)

        if top is None and secret:
            # Не найденную секретную не показываем вовсе — только считаем,
            # и считаем на её уровне: «в золоте есть что искать» ничего
            # не выдаёт, но объясняет пустую вкладку.
            level = nxt.tier.value if nxt else Tier.PLATINUM.value
            summary.secrets_left[level] = summary.secrets_left.get(level, 0) + 1
            continue

        # Чужая секретная, которую смотрящий сам не открыл: трофей виден,
        # название и условие — нет. Иначе достаточно заглянуть к любому
        # старожилу, чтобы узнать их все, и искать станет нечего.
        masked = secret and top is not None and top.code not in seen

        state = GroupState(
            group=group,
            label=GROUP_LABEL.get(group, ladder[-1].description),
            secret=secret,
            hidden=masked,
            tier=top.tier if top else None,
            emoji=TIER_EMOJI[top.tier] if top else "",
            title=HIDDEN_TITLE if masked else (top.title if top else ""),
            description=HIDDEN_HINT if masked else (top.description if top else ""),
            earned_at=earned.get(top.code) if top else None,
            next_title=nxt.title if nxt else None,
            next_description=nxt.description if nxt else None,
            next_tier=nxt.tier if nxt else None,
            # Прогресс к следующей ступени. Взята платина — расти некуда.
            progress=min(counts.get(nxt.metric, 0), nxt.target) if nxt else 0,
            target=nxt.target if nxt else 0,
            steps=[
                Step(
                    tier=rule.tier,
                    title=HIDDEN_TITLE if masked else rule.title,
                    description=HIDDEN_HINT if masked else rule.description,
                    # У скрытой и порог не показываем: «1 из 1» ничего не даёт,
                    # а у счётной цели выдал бы, что именно считают.
                    target=1 if masked else rule.target,
                    # Прогресс по своей ступени: у взятой он полный, даже если
                    # показатель потом просел — награду не отбирают.
                    progress=(
                        rule.target
                        if rule.code in earned
                        else min(counts.get(rule.metric, 0), rule.target)
                    )
                    if not masked
                    else 1,
                    earned_at=earned.get(rule.code),
                )
                for rule in ladder
            ],
        )
        summary.groups.append(state)

        if top is not None:
            setattr(summary, top.tier.value, getattr(summary, top.tier.value) + 1)

    # Порядок не трогаем: цели идут теми же строками, что в таблице клуба.
    # Сортировка по «ближе всего» путала бы — список менялся бы местами
    # от каждой отметки.
    return summary


class AchievementError(ValueError):
    """Причину показываем администратору как есть."""


async def grant(
    session: AsyncSession,
    actor_id: int,
    user_id: int,
    title: str,
    description: str,
    tier: str,
) -> Achievement:
    """Именная ачивка от администратора.

    Придумывается на месте под конкретного человека — «за то, что притащил
    проектор», — поэтому её текст живёт в строке, а не в реестре. В остальном
    она обычная: считается в тех же четырёх числах и лежит во вкладке своего
    уровня.
    """
    if tier not in set(Tier):
        raise AchievementError("Неизвестный уровень")
    if not title.strip():
        raise AchievementError("У ачивки должно быть название")

    person = await session.get(User, user_id)
    if person is None or not person.is_active:
        raise AchievementError("Участник не найден")

    row = Achievement(
        user_id=user_id,
        # Суффикс случайный: одному человеку можно выдать несколько именных,
        # а уникальность пары (человек, код) держит индекс.
        code=f"{CUSTOM_PREFIX}{secrets.token_hex(6)}",
        title=title.strip(),
        description=description.strip(),
        tier=tier,
        granted_by=actor_id,
    )
    session.add(row)
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="achievement",
            entity_id=user_id,
            action="grant",
            payload={"title": row.title, "tier": tier},
        )
    )
    await session.flush()
    await notify.queue(
        session,
        user_id,
        NotificationKind.ACHIEVEMENT_EARNED,
        dedup_key=f"achievement:{user_id}:{row.code}",
        payload={
            "emoji": TIER_EMOJI[Tier(tier)],
            "tier": TIER_LABEL[Tier(tier)],
            "title": row.title,
            "hint": row.description,
            "custom": True,
        },
    )
    await session.commit()
    return row


async def revoke(session: AsyncSession, actor_id: int, achievement_id: int) -> None:
    """Снимает именную ачивку. Заслуженные автоматом не трогаем — их не отбирают."""
    row = await session.get(Achievement, achievement_id)
    if row is None or row.title is None:
        raise AchievementError("Именная ачивка не найдена")
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity="achievement",
            entity_id=row.user_id,
            action="revoke",
            payload={"title": row.title},
        )
    )
    await session.delete(row)
    await session.commit()


async def granted_by_hand(session: AsyncSession) -> list[tuple[Achievement, str]]:
    """Все именные с именами получателей — список для админки."""
    rows = await session.execute(
        sa.select(Achievement, User.display_name)
        .join(User, User.id == Achievement.user_id)
        .where(Achievement.title.is_not(None))
        .order_by(Achievement.earned_at.desc())
    )
    return [(row, name) for row, name in rows]


async def award(session: AsyncSession) -> int:
    """Выдаёт всё заслуженное и поздравляет. Идемпотентна.

    Пройденные ступени остаются: в профиле они горят как взятые, и отбирать
    у человека бронзу за то, что он дорос до серебра, незачем. Трофей у цели
    при этом всё равно один — высший: числа считает `of_user` по верхней
    достигнутой, а не по числу строк.

    Поздравляем только за высшую новую: три сообщения подряд за один рывок
    читаются как сбой, а не как награда. Возвращает число новых ступеней.
    """
    counts = await metrics(session)
    if not counts:
        return 0

    known: dict[int, set[str]] = {}
    for user_id, code in await session.execute(
        sa.select(Achievement.user_id, Achievement.code).where(
            Achievement.user_id.in_(list(counts))
        )
    ):
        known.setdefault(user_id, set()).add(code)

    active = set(
        (await session.execute(sa.select(User.id).where(User.is_active, User.id.in_(list(counts)))))
        .scalars()
        .all()
    )

    given = 0
    for user_id, values in counts.items():
        if user_id not in active:
            continue
        mine = known.get(user_id, set())
        for ladder in LADDERS.values():
            # Из достигнутых ступеней берём высшую: перепрыгнув через бронзу,
            # человек получает сразу серебро, а не две ачивки подряд.
            reached = [
                rule for rule in ladder if values.get(rule.metric, 0) >= rule.target
            ]
            if not reached:
                continue
            top = reached[-1]
            if top.code in mine:
                continue

            # Записываем все пройденные ступени, а не одну верхнюю: перепрыгнув
            # через бронзу, человек её всё равно прошёл, и в профиле она должна
            # гореть. Заодно это чинит тех, у кого низшие когда-то снимались.
            # ON CONFLICT, а не проверка выше: два прохода разом не должны
            # ронять всю пачку на уникальном ключе.
            fresh = False
            for rule in reached:
                created = await session.execute(
                    insert(Achievement)
                    .values(user_id=user_id, code=rule.code)
                    .on_conflict_do_nothing(index_elements=[Achievement.user_id, Achievement.code])
                    .returning(Achievement.id)
                )
                if created.scalar_one_or_none() is not None and rule.code == top.code:
                    fresh = True
            if not fresh:
                continue

            # Следующая ступень той же цели — её называем прямо в сообщении.
            ahead = next((rule for rule in ladder if rule.rank > top.rank), None)
            await notify.queue(
                session,
                user_id,
                NotificationKind.ACHIEVEMENT_EARNED,
                dedup_key=f"achievement:{user_id}:{top.code}",
                payload={
                    "emoji": TIER_EMOJI[top.tier],
                    "tier": TIER_LABEL[top.tier],
                    "title": top.title,
                    "hint": top.description,
                    "secret": top.secret,
                    "next_title": ahead.title if ahead else None,
                    "next_hint": ahead.description if ahead else None,
                },
            )
            given += 1

    await session.commit()
    if given:
        logger.info("Выдано ачивок: %d", given)
    return given
