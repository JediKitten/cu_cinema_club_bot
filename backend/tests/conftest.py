"""Тесты идут в отдельной БД cinema_test — прогон не должен трогать рабочие данные.

Движок создаётся на каждый тест: asyncpg-соединение привязано к event loop,
а pytest-asyncio даёт каждому тесту свой. Схема при этом разворачивается один раз.
"""

from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_config
from app.models import Base

TEST_DB = "cinema_test"
_schema_ready = False


def _url(database: str) -> str:
    return get_config().database_url.rsplit("/", 1)[0] + f"/{database}"


async def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return

    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            await conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()

    engine = create_async_engine(_url(TEST_DB))
    async with engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    _schema_ready = True


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    await _ensure_schema()
    engine = create_async_engine(_url(TEST_DB))
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with maker() as session:
        yield session
        await session.rollback()
        # Каждый тест начинает с чистых таблиц: рейтинги считаются по всей базе,
        # остатки от соседнего теста молча исказили бы результат.
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await session.execute(sa.text(f"TRUNCATE TABLE {tables} CASCADE"))
        await session.commit()

    await engine.dispose()
