"""Импорт стартового каталога.

Какие фильмы завозить — решает топ-250 Кинопоиска (курируемый рейтинг, а не
просто самое популярное). Сами данные берём из TMDB по `externalId.tmdb`,
как требует §11: TMDB — основа каталога, Кинопоиск лишь подсказывает список.

Запуск:  ./venv/bin/python -m app.import_top --limit 100
"""

import argparse
import asyncio
import logging

import sqlalchemy as sa

from app.db import SessionLocal
from app.models import Film
from app.services.kinopoisk import KinopoiskError, get_kinopoisk, upsert_from_kinopoisk
from app.services.tmdb import TmdbError, get_tmdb, upsert_from_tmdb

logger = logging.getLogger("import_top")


async def run_kinopoisk(limit: int) -> int:
    """Каталог целиком из Кинопоиска — когда TMDB недоступен.

    Отличается от основного пути не только источником данных: постеры тоже
    поедут с CDN Кинопоиска, а он, в отличие от image.tmdb.org, доступен там же,
    где и сам API.
    """
    kinopoisk = get_kinopoisk()
    if not kinopoisk.configured:
        raise SystemExit("KINOPOISK_API_TOKEN не задан в .env")

    logger.info("Забираем топ-%d Кинопоиска…", limit)
    try:
        docs = await kinopoisk.top250_full(limit)
    except KinopoiskError as exc:
        raise SystemExit(f"Не удалось получить список: {exc}") from exc

    imported = 0
    async with SessionLocal() as session:
        for doc in docs:
            film = await upsert_from_kinopoisk(session, doc)
            imported += 1
            logger.info("#%-3s %s (%s)", doc.get("top250", "?"), film.title_ru, film.year or "—")

    total = await _count_films()
    logger.info("Готово. Импортировано: %d. Всего в каталоге: %d", imported, total)
    await kinopoisk.aclose()
    return imported


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
    parser.add_argument("--limit", type=int, default=100, help="сколько позиций топ-250 брать")
    parser.add_argument(
        "--delay", type=float, default=0.1, help="пауза между запросами к TMDB, секунд"
    )
    parser.add_argument(
        "--source",
        choices=("tmdb", "kinopoisk"),
        default="tmdb",
        help="откуда брать данные: tmdb (по §11) или kinopoisk (когда TMDB недоступен)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.source == "kinopoisk":
        asyncio.run(run_kinopoisk(args.limit))
    else:
        asyncio.run(run(args.limit, args.delay))


if __name__ == "__main__":
    main()
