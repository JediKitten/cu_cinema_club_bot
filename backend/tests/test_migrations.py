"""Миграции на чистой базе.

Тесты разворачивают схему через `Base.metadata.create_all` — быстро, но это
не тот путь, которым обновляется бой: там работает `alembic upgrade head`,
прямо при старте контейнера api. Пока эти два пути не сверяются, забытая
миграция обнаруживается на живой базе во время выкладки.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base
from tests.conftest import _url

MIGRATION_DB = "cinema_migrations"
BACKEND = Path(__file__).resolve().parent.parent

# Расхождения, которые действительно ломают выкладку. Мелочи вроде разницы
# в server_default alembic видит и там, где обе стороны верны, — на них
# ориентироваться нельзя.
BREAKING = {"add_table", "remove_table", "add_column", "remove_column"}


def _alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": _url(MIGRATION_DB)},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} упал:\n{result.stdout}\n{result.stderr}")


async def _recreate_database() -> None:
    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
        await conn.execute(sa.text(f'CREATE DATABASE "{MIGRATION_DB}"'))
    await admin.dispose()


def _differences(sync_conn) -> list:
    context = MigrationContext.configure(sync_conn)
    return [
        diff
        for diff in compare_metadata(context, Base.metadata)
        # Вложенные диффы (изменения внутри таблицы) приезжают списками.
        for diff in (diff if isinstance(diff, list) else [diff])
        if diff[0] in BREAKING
    ]


async def test_upgrade_head_builds_the_same_schema_as_the_models():
    """`alembic upgrade head` на пустой базе должен дать схему из моделей.

    Расхождение здесь означает либо забытую миграцию, либо миграцию, которая
    делает не то, что описывает модель, — и то и другое видно только в бою.
    """
    await _recreate_database()
    _alembic("upgrade", "head")

    engine = create_async_engine(_url(MIGRATION_DB))
    try:
        async with engine.connect() as conn:
            diffs = await conn.run_sync(_differences)
    finally:
        await engine.dispose()

    assert diffs == [], f"схема миграций разошлась с моделями: {diffs}"


async def test_downgrade_unwinds_everything():
    """Откат описан в deploy/README как способ спасения — значит он должен работать."""
    await _recreate_database()
    _alembic("upgrade", "head")
    _alembic("downgrade", "base")

    engine = create_async_engine(_url(MIGRATION_DB))
    try:
        async with engine.connect() as conn:
            left = await conn.run_sync(lambda c: sa.inspect(c).get_table_names())
    finally:
        await engine.dispose()

    # Своя таблица версий у alembic остаётся — это его служебная запись.
    assert [name for name in left if name != "alembic_version"] == []
