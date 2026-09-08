"""Лента фильмов для быстрой разметки (расширение по просьбе клуба).

Карточка на весь экран: свайп вправо — «хочу посмотреть», влево — «не моё»,
кнопка «уже смотрел». Смысл в скорости: отметить сотню фильмов списком никто
не станет, а пролистать полсотни карточек — минута.

Показываем только то, о чём человек ещё ничего не сказал: без отметки, без
оценки, без просмотра и без отказа. Иначе лента возвращала бы одно и то же.

Порядок карточек — рекомендация, а не топ каталога. Просто «самое популярное»
у всех одинаково и заканчивается на второй сотне одинаковых блокбастеров,
поэтому очередь складывается из нескольких сигналов сразу: что высоко оценили
друзья, что они хотят смотреть, насколько фильм похож на то, что человек уже
любит, что отмечают в клубе, — и лишь в последнюю очередь внешний рейтинг.
Плюс постоянная доля случайности, чтобы у неизвестного фильма тоже был шанс.
"""

import math
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Favourite, Film, FilmRating, FilmSkip, Friendship, Interest, Watch
from app.models.enums import FilmStatus

# Сколько карточек отдаём за раз. Полтора экрана свайпов: дозагрузка успевает
# случиться незаметно, а лишнего не тянем.
PAGE = 24

# Оценка «нормально» — 3 звезды, то есть 6 полубаллов. Ниже неё оценка ничего
# не рекомендует, поэтому все шкалы отсчитываются от этой точки, а не от нуля.
NEUTRAL = 6

# Вклад каждого сигнала. Все слагаемые приведены к 0..1, так что веса читаются
# напрямую: оценка друга весит вдвое больше сходства со вкусом и втрое — больше
# внешней известности.
W_FRIENDS_LOVE = 3.0  # друзья высоко оценили
W_FRIENDS_WANT = 1.5  # друзья отметили «хочу посмотреть»
W_TASTE = 2.0  # жанры и режиссёры, которые человек уже любит
W_CLUB_LOVE = 1.2  # средняя оценка клуба
W_CLUB_WANT = 1.0  # сколько людей отметили фильм
W_KNOWN = 1.0  # внешний рейтинг и известность
W_CHANCE = 0.6  # случайность: меньше любого содержательного сигнала, но
# достаточно, чтобы порядок не был одним и тем же списком у всех

# Сколько оценок клуба считаем достаточными, чтобы верить средней.
CLUB_CONFIDENT = 3
# Скольких отметок хватает, чтобы «фильм ждут» звучало убедительно.
CLUB_WANTED = 5
FRIENDS_WANTED = 2
# Известность считаем в логарифме голосов: разница между 1000 и 5000 заметна,
# между 500 000 и 900 000 — уже нет.
FAMOUS_VOTES = math.log(200_000)

# Вклад источников во вкус: любимое в профиле человек выбрал сам, отметка —
# намерение, оценка — приговор. Отсюда и порядок.
TASTE_FAVOURITE = 1.0
TASTE_MARK = 0.6
# Сколько жанров и режиссёров держим в профиле вкуса: длинный хвост из одного
# случайного фильма превратил бы рекомендацию обратно в общий топ.
TASTE_GENRES = 6
TASTE_DIRECTORS = 5
TASTE_FLOOR = 0.15


@dataclass(frozen=True, slots=True)
class Taste:
    """Что человек любит, в долях от самого любимого (0..1)."""

    genres: dict[str, float] = field(default_factory=dict)
    directors: dict[str, float] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.genres and not self.directors


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Карточка ленты и причина, по которой она здесь.

    Причину показываем на экране: рекомендация без объяснения выглядит
    случайной, а «друг оценил на 5» решает за человека быстрее любого рейтинга.
    """

    film: Film
    reason: str | None = None


def _spoken_for(user_id: int):
    """Фильмы, о которых человек уже высказался: отметил, оценил, посмотрел,
    пролистнул.

    Один запрос на все случаи — иначе «уже размечено» пришлось бы держать
    в нескольких местах и они бы разъехались.
    """
    return sa.union(
        sa.select(Interest.film_id).where(
            Interest.user_id == user_id, Interest.revoked_at.is_(None)
        ),
        sa.select(FilmRating.film_id).where(FilmRating.user_id == user_id),
        sa.select(Watch.film_id).where(Watch.user_id == user_id),
        sa.select(FilmSkip.film_id).where(FilmSkip.user_id == user_id),
    )


def _clip(expr):
    """Слагаемое в 0..1: без этого один восторженный друг перевешивал бы всё."""
    return sa.func.least(sa.func.greatest(expr, 0.0), 1.0)


async def taste(session: AsyncSession, user_id: int) -> Taste:
    """Профиль вкуса: жанры и режиссёры, которые человек уже выбирал.

    Считается по тому, что и так есть, — оценкам, отметкам и любимому в профиле.
    Ничего специально ради рекомендаций не сохраняется.
    """
    rated = (
        sa.select(
            Film.genres.label("genres"),
            Film.directors.label("directors"),
            ((FilmRating.score - NEUTRAL) / 4.0).label("weight"),
        )
        .join(FilmRating, FilmRating.film_id == Film.id)
        .where(FilmRating.user_id == user_id, FilmRating.score > NEUTRAL)
    )
    marked = (
        sa.select(
            Film.genres,
            Film.directors,
            sa.literal(TASTE_MARK),
        )
        .join(Interest, Interest.film_id == Film.id)
        .where(Interest.user_id == user_id, Interest.revoked_at.is_(None))
    )
    favourite = (
        sa.select(
            Film.genres,
            Film.directors,
            sa.literal(TASTE_FAVOURITE),
        )
        .join(Favourite, Favourite.film_id == Film.id)
        .where(Favourite.user_id == user_id)
    )

    genres: dict[str, float] = {}
    directors: dict[str, float] = {}
    rows = await session.execute(sa.union_all(rated, marked, favourite))
    for film_genres, film_directors, weight in rows:
        for name in film_genres or ():
            genres[name] = genres.get(name, 0.0) + float(weight)
        for name in film_directors or ():
            directors[name] = directors.get(name, 0.0) + float(weight)

    def top(values: dict[str, float], keep: int) -> dict[str, float]:
        if not values:
            return {}
        # Нормируем по самому любимому: важна не сумма, а расстановка. Иначе
        # человек с сотней отметок получал бы веса на порядок больше новичка,
        # и один и тот же коэффициент значил бы у них разное.
        peak = max(values.values())
        if peak <= 0:
            return {}
        ranked = sorted(values.items(), key=lambda item: item[1], reverse=True)[:keep]
        return {name: value / peak for name, value in ranked if value / peak >= TASTE_FLOOR}

    return Taste(genres=top(genres, TASTE_GENRES), directors=top(directors, TASTE_DIRECTORS))


def _taste_expr(profile: Taste):
    """Насколько фильм похож на то, что человек уже любит (0..1).

    Совпадения складываются: два любимых жанра убедительнее одного, но выше
    единицы сумма не поднимается — иначе комедийная драма всегда обходила бы
    фильм, который друзья оценили на пять.
    """
    if profile.empty:
        return sa.literal(0.0)

    terms = [
        sa.case((Film.genres.any(name), weight), else_=0.0)
        for name, weight in profile.genres.items()
    ]
    terms += [
        sa.case((Film.directors.any(name), weight), else_=0.0)
        for name, weight in profile.directors.items()
    ]
    return _clip(sum(terms[1:], terms[0]) / 2.0)


def _chance_expr(user_id: int):
    """Постоянная случайность: у каждого своя, но одна и та же между запросами.

    Настоящий random() перетасовывал бы очередь на каждой дозагрузке, и карточки
    то повторялись бы, то пропадали, не показавшись. Хеш от пары (фильм,
    человек) даёт ту же непредсказуемость, но порядок при этом устойчив.
    """
    return sa.literal_column(
        f"(('x' || substr(md5(films.id::text || ':{int(user_id)}'), 1, 8))::bit(32)::int"
        " / 4294967296.0 + 0.5)"
    )


async def next_films(
    session: AsyncSession,
    user_id: int,
    limit: int = PAGE,
    exclude: list[int] | None = None,
) -> list[Suggestion]:
    """Следующие карточки — по рекомендации, а не по одной популярности."""
    profile = await taste(session, user_id)
    friend_ids = sa.select(Friendship.friend_id).where(Friendship.user_id == user_id)

    friends_rated = (
        sa.select(
            FilmRating.film_id.label("film_id"),
            sa.func.sum(sa.func.greatest(FilmRating.score - NEUTRAL, 0)).label("love"),
            sa.func.avg(FilmRating.score).label("average"),
            sa.func.count().label("votes"),
        )
        .where(FilmRating.user_id.in_(friend_ids))
        .group_by(FilmRating.film_id)
        .subquery("friends_rated")
    )
    friends_want = (
        sa.select(
            Interest.film_id.label("film_id"),
            sa.func.count(sa.distinct(Interest.user_id)).label("people"),
        )
        .where(Interest.revoked_at.is_(None), Interest.user_id.in_(friend_ids))
        .group_by(Interest.film_id)
        .subquery("friends_want")
    )
    club_rated = (
        sa.select(
            FilmRating.film_id.label("film_id"),
            sa.func.avg(FilmRating.score).label("average"),
            sa.func.count().label("votes"),
        )
        .group_by(FilmRating.film_id)
        .subquery("club_rated")
    )
    club_want = (
        sa.select(
            Interest.film_id.label("film_id"),
            sa.func.count(sa.distinct(Interest.user_id)).label("people"),
        )
        .where(Interest.revoked_at.is_(None))
        .group_by(Interest.film_id)
        .subquery("club_want")
    )

    friend_love = sa.func.coalesce(friends_rated.c.love, 0)
    friend_avg = friends_rated.c.average
    friend_votes = sa.func.coalesce(friends_rated.c.votes, 0)
    friend_people = sa.func.coalesce(friends_want.c.people, 0)
    club_avg = club_rated.c.average
    club_votes = sa.func.coalesce(club_rated.c.votes, 0)
    club_people = sa.func.coalesce(club_want.c.people, 0)

    # Известность: хорошая внешняя оценка, подтверждённая числом голосов.
    # Одна без другой ничего не значит — 9,0 по десяти голосам это не про кино.
    known = _clip((sa.func.coalesce(Film.ext_rating, 0.0) - NEUTRAL) / 2.0) * _clip(
        sa.func.ln(1 + sa.func.coalesce(Film.ext_votes, 0)) / FAMOUS_VOTES
    )

    score = (
        # Один друг с пятёркой (10 полубаллов) даёт полный вес, с четвёркой — половину.
        W_FRIENDS_LOVE * _clip(friend_love / 4.0)
        + W_FRIENDS_WANT * _clip(friend_people / float(FRIENDS_WANTED))
        + W_TASTE * _taste_expr(profile)
        + W_CLUB_LOVE
        * _clip((sa.func.coalesce(club_avg, 0.0) - NEUTRAL) / 4.0)
        * _clip(club_votes / float(CLUB_CONFIDENT))
        + W_CLUB_WANT * _clip(club_people / float(CLUB_WANTED))
        + W_KNOWN * known
        + W_CHANCE * _chance_expr(user_id)
    )

    stmt = (
        sa.select(
            Film,
            friend_avg.label("friend_avg"),
            friend_votes.label("friend_votes"),
            friend_people.label("friend_people"),
            club_avg.label("club_avg"),
            club_votes.label("club_votes"),
            club_people.label("club_people"),
        )
        .outerjoin(friends_rated, friends_rated.c.film_id == Film.id)
        .outerjoin(friends_want, friends_want.c.film_id == Film.id)
        .outerjoin(club_rated, club_rated.c.film_id == Film.id)
        .outerjoin(club_want, club_want.c.film_id == Film.id)
        .where(Film.status == FilmStatus.ACTIVE, Film.id.not_in(_spoken_for(user_id)))
        # id вторым ключом: при равном счёте порядок иначе плавал бы между
        # страницами, и карточки терялись бы на стыке.
        .order_by(score.desc(), Film.id)
        .limit(limit)
    )
    if exclude:
        # То, что уже лежит в очереди на экране: иначе дозагрузка выдала бы
        # те же карточки второй раз.
        stmt = stmt.where(Film.id.not_in(exclude))

    rows = (await session.execute(stmt)).all()
    return [
        Suggestion(
            film=row[0],
            reason=_reason(
                profile,
                row[0],
                friend_avg=row.friend_avg,
                friend_votes=row.friend_votes,
                friend_people=row.friend_people,
                club_avg=row.club_avg,
                club_votes=row.club_votes,
                club_people=row.club_people,
            ),
        )
        for row in rows
    ]


def _stars(score: float) -> str:
    """Полубаллы базы — в звёзды на экране, с запятой."""
    return f"{score / 2:.1f}".replace(".", ",")


def _reason(
    profile: Taste,
    film: Film,
    *,
    friend_avg,
    friend_votes: int,
    friend_people: int,
    club_avg,
    club_votes: int,
    club_people: int,
) -> str | None:
    """Одна строка о том, почему карточка здесь. Сильнейший сигнал побеждает."""
    if friend_votes and friend_avg is not None and float(friend_avg) >= NEUTRAL + 1:
        stars = _stars(float(friend_avg))
        return f"Друг оценил на {stars}" if friend_votes == 1 else f"Друзья оценили на {stars}"

    if friend_people:
        return "Друг хочет посмотреть" if friend_people == 1 else "Друзья хотят посмотреть"

    matched = [name for name in film.genres or () if name in profile.genres]
    director = next((name for name in film.directors or () if name in profile.directors), None)
    if director:
        return "Вы любите фильмы этого режиссёра"
    if matched:
        # Самый весомый из совпавших жанров: он и объясняет попадание.
        best = max(matched, key=lambda name: profile.genres[name])
        return f"Похоже на ваш вкус: {best.lower()}"

    if club_votes >= CLUB_CONFIDENT and club_avg is not None and float(club_avg) >= NEUTRAL + 1:
        return f"В клубе оценили на {_stars(float(club_avg))}"
    if club_people >= CLUB_WANTED:
        return "Фильм ждут в клубе"
    return None


async def skip(session: AsyncSession, user_id: int, film_id: int) -> None:
    """«Не интересно». Повтор ничего не меняет: свайпнуть дважды нельзя,
    но повторный запрос при плохой связи — обычное дело."""
    await session.execute(
        insert(FilmSkip)
        .values(user_id=user_id, film_id=film_id)
        .on_conflict_do_nothing(index_elements=[FilmSkip.user_id, FilmSkip.film_id])
    )
    await session.commit()


async def left(session: AsyncSession, user_id: int) -> int:
    """Сколько карточек ещё не размечено — лента должна говорить, что кончилась."""
    return (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Film)
            .where(Film.status == FilmStatus.ACTIVE, Film.id.not_in(_spoken_for(user_id)))
        )
        or 0
    )
