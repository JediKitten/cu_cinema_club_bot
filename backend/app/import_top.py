"""Импорт стартового каталога.

Какие фильмы завозить — решает топ-250 Кинопоиска (курируемый рейтинг, а не
просто самое популярное). Сами данные берём из TMDB по `externalId.tmdb`,
как требует §11: TMDB — основа каталога, Кинопоиск лишь подсказывает список.

Ленте одного топ-250 мало: карточки в ней кончаются за пару вечеров, поэтому
для наполнения каталога есть широкий список — `--source kinopoisk --list popular`.

Запуск:  ./venv/bin/python -m app.import_top --limit 100
         ./venv/bin/python -m app.import_top --source kinopoisk --list popular --limit 1500
"""

import argparse
import asyncio
import logging

import sqlalchemy as sa

from app.db import SessionLocal
from app.models import Favourite, Film, FilmRating, Interest, Watch
from app.models.enums import FilmStatus
from app.services import matching
from app.services.kinopoisk import KinopoiskError, get_kinopoisk, upsert_from_kinopoisk
from app.services.tmdb import TmdbError, get_tmdb, upsert_from_tmdb

logger = logging.getLogger("import_top")


async def run_kinopoisk(limit: int, listing: str = "top250") -> int:
    """Каталог целиком из Кинопоиска — когда TMDB недоступен.

    Отличается от основного пути не только источником данных: постеры тоже
    поедут с CDN Кинопоиска, а он, в отличие от image.tmdb.org, доступен там же,
    где и сам API.

    `listing` выбирает, что завозить: `top250` — курируемый рейтинг для первого
    наполнения, `popular` — широкий список известного кино. Второй нужен ленте:
    двести пятьдесят карточек человек пролистывает за пару вечеров, и дальше
    рекомендовать становится нечего.
    """
    kinopoisk = get_kinopoisk()
    if not kinopoisk.configured:
        raise SystemExit("KINOPOISK_API_TOKEN не задан в .env")

    logger.info("Забираем %s Кинопоиска (%d)…", listing, limit)
    try:
        docs = (
            await kinopoisk.popular(limit)
            if listing == "popular"
            else await kinopoisk.top250_full(limit)
        )
    except KinopoiskError as exc:
        raise SystemExit(f"Не удалось получить список: {exc}") from exc

    imported = 0
    async with SessionLocal() as session:
        for doc in docs:
            film = await upsert_from_kinopoisk(session, doc)
            imported += 1
            logger.info("%-4d %s (%s)", imported, film.title_ru, film.year or "—")

        # Оценку TMDB Кинопоиск не отдаёт, а сортировать по ней клуб хочет.
        # Идём за ней отдельно — по той самой связке externalId.tmdb.
        if get_tmdb().configured:
            await enrich_tmdb(session)

        await hide_duplicates(session)

    total = await _count_films()
    logger.info("Готово. Импортировано: %d. Всего в каталоге: %d", imported, total)
    await kinopoisk.aclose()
    return imported


async def hide_duplicates(session) -> int:
    """Прячет двойников: тот же фильм, заведённый дважды разными путями.

    Совпадение считаем по названию и году (`matching.keys`) — id разных
    источников у двойников по определению не совпадают. Прячем только строку,
    к которой никто не притрагивался: если фильм кто-то отметил, оценил или
    посмотрел, он остаётся, даже когда выглядит копией.
    """
    hidden = 0
    films = list(
        (
            await session.execute(
                sa.select(Film).where(Film.status == FilmStatus.ACTIVE).order_by(Film.id)
            )
        )
        .scalars()
        .all()
    )
    marks = await _activity(session)

    seen: dict[tuple[str, int], Film] = {}
    for film in films:
        keys = matching.keys(film.title_ru, film.title_orig, film.year)
        twin = next((seen[key] for key in keys if key in seen), None)

        if twin is not None:
            # Остаётся тот, за кем больше следов; при равенстве — тот, что
            # с данными Кинопоиска: у него русское описание и живой постер.
            keep, drop = sorted(
                (twin, film),
                key=lambda f: (marks.get(f.id, 0), f.kp_id is not None),
                reverse=True,
            )
            if marks.get(drop.id, 0) > 0:
                # За обоими что-то стоит: склеивать вслепую нельзя, чужие
                # отметки при этом потерялись бы. Оставляем как есть.
                continue
            drop.status = FilmStatus.HIDDEN
            hidden += 1
            logger.info("Двойник: прячем «%s» (%s)", drop.title_ru, drop.year or "—")
            keys |= matching.keys(keep.title_ru, keep.title_orig, keep.year)
            film = keep

        for key in keys:
            seen[key] = film

    await session.commit()
    if hidden:
        logger.info("Спрятано двойников: %d", hidden)
    return hidden


async def _activity(session) -> dict[int, int]:
    """Сколько следов оставили люди на каждом фильме — отметки, оценки, просмотры."""
    counts: dict[int, int] = {}
    for table in (Interest.film_id, FilmRating.film_id, Watch.film_id, Favourite.film_id):
        rows = await session.execute(sa.select(table, sa.func.count()).group_by(table))
        for film_id, count in rows:
            counts[film_id] = counts.get(film_id, 0) + count
    return counts


async def enrich_tmdb(session, batch: int = 16) -> int:
    """Проставляет рейтинг TMDB фильмам, у которых он ещё не известен.

    Проход идемпотентный и возобновляемый: берём только те строки, где рейтинга
    нет, поэтому прерванный импорт можно просто запустить заново, а не начинать
    с начала. Запросы идут пачками — по одному полторы тысячи фильмов заняли бы
    десяток минут.
    """
    tmdb = get_tmdb()
    logger.info("Подтягиваем оценки TMDB…")
    filled = failed = 0

    rows = (
        await session.execute(
            sa.select(Film.id, Film.tmdb_id).where(
                Film.tmdb_id.is_not(None), Film.tmdb_rating.is_(None)
            )
        )
    ).all()

    for start in range(0, len(rows), batch):
        chunk = rows[start : start + batch]
        payloads = await asyncio.gather(
            *(tmdb.movie(tmdb_id) for _, tmdb_id in chunk), return_exceptions=True
        )
        for (film_id, _), payload in zip(chunk, payloads, strict=True):
            if isinstance(payload, BaseException) or not payload.get("vote_count"):
                failed += 1
                continue
            await session.execute(
                sa.update(Film)
                .where(Film.id == film_id)
                .values(
                    tmdb_rating=payload.get("vote_average"),
                    tmdb_votes=payload.get("vote_count"),
                )
            )
            filled += 1
        await session.commit()

    logger.info("Оценки TMDB: проставлено %d, не вышло %d", filled, failed)
    return filled


async def run(limit: int, delay: float) -> int:
    tmdb = get_tmdb()
    kinopoisk = get_kinopoisk()

    if not tmdb.configured:
        raise SystemExit("TMDB_API_TOKEN не задан в .env")
    if not kinopoisk.configured:
        raise SystemExit("KINOPOISK_API_TOKEN не задан в .env")

    logger.info("Забираем топ-%d Кинопоиска…", limit)
    try:
        entries = await kinopoisk.top250(limit)
    except KinopoiskError as exc:
        raise SystemExit(f"Не удалось получить список: {exc}") from exc
    logger.info("Получено позиций: %d", len(entries))

    imported = matched_by_search = skipped = failed = 0

    async with SessionLocal() as session:
        for entry in entries:
            tmdb_id = entry.tmdb_id
            by_search = False

            if tmdb_id is None:
                # У части позиций Кинопоиск не знает tmdb id — среди них советская
                # классика, ради которой клуб и затевается. Ищем в TMDB сами.
                tmdb_id = await _find_in_tmdb(tmdb, entry)
                by_search = tmdb_id is not None
                if tmdb_id is None:
                    logger.warning("#%-3d %s — в TMDB не найден", entry.rank, entry.name)
                    skipped += 1
                    continue

            try:
                payload = await tmdb.movie(tmdb_id)
            except TmdbError as exc:
                logger.error("#%-3d %s — TMDB: %s", entry.rank, entry.name, exc)
                failed += 1
                continue

            matched_by_search += by_search

            film = await upsert_from_tmdb(session, payload)
            # Связку с Кинопоиском сохраняем сразу: она понадобится для ленивой
            # подгрузки русского рейтинга и избавит от повторного поиска.
            if film.kp_id != entry.kp_id:
                await session.execute(
                    sa.update(Film).where(Film.id == film.id).values(kp_id=entry.kp_id)
                )
                await session.commit()

            imported += 1
            logger.info("#%-3d %s (%s)", entry.rank, film.title_ru, film.year or "—")

            # Своя пауза поверх лимита клиента: импорт не должен упираться
            # в rate limit TMDB и получать 429.
            if delay:
                await asyncio.sleep(delay)

    total = await _count_films()
    logger.info(
        "Готово. Импортировано: %d (из них найдено поиском: %d), "
        "не найдено: %d, с ошибкой: %d. Всего в каталоге: %d",
        imported,
        matched_by_search,
        skipped,
        failed,
        total,
    )
    await tmdb.aclose()
    await kinopoisk.aclose()
    return imported


async def _find_in_tmdb(tmdb, entry) -> int | None:
    """Подбор tmdb id по названию и году.

    Год обязателен для совпадения: у популярных названий есть ремейки, и без
    проверки года в каталог легко завезти не тот фильм. Оригинальное название
    пробуем первым — русское TMDB часто не знает.
    """
    queries = [q for q in (entry.alternative_name, entry.name) if q]
    for query in queries:
        try:
            results = await tmdb.search(query)
        except TmdbError:
            return None
        for item in results:
            release = item.get("release_date") or ""
            year = int(release[:4]) if release[:4].isdigit() else None
            if entry.year is None or year == entry.year:
                return item["id"]
    return None


async def _count_films() -> int:
    async with SessionLocal() as session:
        return await session.scalar(sa.select(sa.func.count()).select_from(Film)) or 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт стартового каталога фильмов")
    parser.add_argument("--limit", type=int, default=100, help="сколько фильмов брать из списка")
    parser.add_argument(
        "--delay", type=float, default=0.1, help="пауза между запросами к TMDB, секунд"
    )
    parser.add_argument(
        "--source",
        choices=("tmdb", "kinopoisk"),
        default="tmdb",
        help="откуда брать данные: tmdb (по §11) или kinopoisk (когда TMDB недоступен)",
    )
    parser.add_argument(
        "--list",
        dest="listing",
        choices=("top250", "popular"),
        default="top250",
        help="что завозить: top250 (курируемый рейтинг) или popular (широкий список для ленты)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.source == "kinopoisk":
        asyncio.run(run_kinopoisk(args.limit, args.listing))
    else:
        asyncio.run(run(args.limit, args.delay))


if __name__ == "__main__":
    main()
