"""Склейка двойников каталога — из командной строки.

Импорт прячет двойников сам, но только тех, за которыми никто не стоит:
пару, где у обеих карточек есть отметки людей, он оставляет человеку. Этот
скрипт и есть тот человек.

    ./venv/bin/python -m app.merge_duplicates                 # показать пары
    ./venv/bin/python -m app.merge_duplicates --merge 314 211  # склеить
    ./venv/bin/python -m app.merge_duplicates --merge-all      # склеить все

Ничего не удаляет: вторая карточка прячется, а всё, что люди про неё сказали,
переезжает на первую.
"""

import argparse
import asyncio
import logging

from app.db import SessionLocal
from app.services import catalog

logger = logging.getLogger("merge_duplicates")


async def show() -> None:
    async with SessionLocal() as session:
        pairs = await catalog.duplicates(session)
        if not pairs:
            logger.info("Двойников не нашлось.")
            return
        logger.info("Найдено пар: %d", len(pairs))
        for pair in pairs:
            logger.info(
                "  оставить %s «%s» (%s, следов %d)  ←  убрать %s (%s, следов %d)",
                pair.keep.id,
                pair.keep.title_ru,
                pair.keep.year or "—",
                pair.keep_traces,
                pair.drop.id,
                pair.drop.year or "—",
                pair.drop_traces,
            )
        logger.info("Склеить:  --merge <оставить> <убрать>   или   --merge-all")


async def merge_one(keep_id: int, drop_id: int) -> None:
    async with SessionLocal() as session:
        moved = await catalog.merge(session, keep_id, drop_id)
        logger.info("Склеено %s ← %s. Перенесено: %s", keep_id, drop_id, moved or "нечего")


async def merge_all() -> None:
    async with SessionLocal() as session:
        pairs = await catalog.duplicates(session)
        for pair in pairs:
            moved = await catalog.merge(session, pair.keep.id, pair.drop.id)
            logger.info(
                "Склеено «%s»: %s ← %s. Перенесено: %s",
                pair.keep.title_ru,
                pair.keep.id,
                pair.drop.id,
                moved or "нечего",
            )
        logger.info("Готово, пар обработано: %d", len(pairs))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Склейка двойников каталога")
    parser.add_argument(
        "--merge", nargs=2, type=int, metavar=("ОСТАВИТЬ", "УБРАТЬ"), help="склеить пару"
    )
    parser.add_argument("--merge-all", action="store_true", help="склеить все найденные пары")
    args = parser.parse_args()

    if args.merge:
        asyncio.run(merge_one(*args.merge))
    elif args.merge_all:
        asyncio.run(merge_all())
    else:
        asyncio.run(show())


if __name__ == "__main__":
    main()
