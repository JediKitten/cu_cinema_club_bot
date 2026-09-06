"""Тесты идут в отдельной БД cinema_test — прогон не должен трогать рабочие данные.

Движок создаётся на каждый тест: asyncpg-соединение привязано к event loop,
а pytest-asyncio даёт каждому тесту свой. Схема при этом разворачивается один раз.
"""

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_config
from app.models import Base
from app.services import rounds as rounds_service
from app.services.settings import SettingsService

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


# --- Общее для API-тестов ---------------------------------------------------

BOT_TOKEN = "123456:TEST-TOKEN-FOR-SIGNATURE-CHECKS"
SUPERADMIN_TG_ID = 777001


def make_init_data(tg_id: int, first_name: str, token: str = BOT_TOKEN) -> str:
    """Подписываем initData ровно так же, как это делает Telegram."""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF_test",
        "user": json.dumps(
            {"id": tg_id, "first_name": first_name, "username": f"u{tg_id}"},
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
async def client(session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("BOOTSTRAP_SUPERADMIN_TG_ID", str(SUPERADMIN_TG_ID))
    get_config.cache_clear()

    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    get_config.cache_clear()


async def login(client, tg_id: int, name: str) -> dict:
    response = await client.post(
        "/api/auth/telegram", json={"init_data": make_init_data(tg_id, name)}
    )
    assert response.status_code == 200, response.text
    return response.json()




# --- Шорт-лист --------------------------------------------------------------


async def set_shortlist(session, round_, film_ids: list[int], actor_id: int):
    """Собирает шорт-лист внутри окна сборки (среда 20:00 — четверг 08:00).

    Само окно проверяется отдельным тестом; остальным незачем зависеть от того,
    в какой день недели случился прогон.
    """
    values = await SettingsService(session).all()
    window = rounds_service.shortlist_window(round_.week_start, values)
    return await rounds_service.set_shortlist(
        session, round_, film_ids, actor_id, now=window.opens_at
    )


async def open_shortlist_window(session) -> None:
    """То же для тестов, которые ходят через HTTP: там «сейчас» не подменишь,
    поэтому раздвигаем само окно на всю неделю, предшествующую неделе показов.
    """
    await SettingsService(session).set_many(
        {"stage1_cut_at": "0 00:00", "stage1_autopilot_at": "6 23:59"}, None
    )
    await session.commit()
