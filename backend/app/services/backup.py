"""Ночная копия базы.

Раньше копии снимались только руками перед рискованным выкатом и лежали на
том же диске, что и сама база: умри диск — и вместе с ним ушло бы всё, копии
в том числе. Теперь копия снимается раз в сутки сама, хранится на сервере
последние `KEEP` штук, а свежая уходит главному админу в Telegram — это и есть
копия за пределами сервера, без отдельного хранилища.

Формат тот же, что у ручных дампов: `pg_dump` в SQL, сжатый gzip. Восстановление
одно на оба случая — `gunzip -c файл | psql` (см. deploy/README.md).
"""

import asyncio
import contextlib
import gzip
import os
from datetime import datetime, time, timedelta, tzinfo
from pathlib import Path

from sqlalchemy.engine import make_url

# Ночью: в это время никто не голосует и не отмечается, и нагрузка на базу
# от дампа никому не мешает.
BACKUP_HOUR = 4

# Две недели копий — ~10 МБ при нынешнем размере базы. Больше хранить
# незачем: к двухнедельной давности откатываться не станет никто.
KEEP = 14

PREFIX = "cinema-"
SUFFIX = ".sql.gz"


class BackupError(RuntimeError):
    """pg_dump завершился с ошибкой — текст ошибки внутри."""


def copies(directory: Path) -> list[Path]:
    """Копии, снятые этим модулем, от старых к новым.

    Имя содержит время снятия, поэтому сортировка по имени — это сортировка
    по времени, и она не зависит от того, трогал ли кто-нибудь файлы.
    """
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.name.startswith(PREFIX) and path.name.endswith(SUFFIX)
    )


def last_deadline(now: datetime) -> datetime:
    """Последний момент, к которому копия уже должна была быть снята."""
    today = datetime.combine(now.date(), time(BACKUP_HOUR), tzinfo=now.tzinfo)
    return today if now >= today else today - timedelta(days=1)


def is_due(directory: Path, now: datetime) -> bool:
    """Нужна ли копия прямо сейчас.

    Сверяемся не с таймером, а с тем, что лежит на диске: бот перезапускается,
    и таймер в памяти после рестарта не знал бы, была ли копия. Первый запуск
    на чистом сервере даёт копию сразу, не дожидаясь ночи.
    """
    deadline = last_deadline(now)
    return not any(
        (taken := stamp(path, now.tzinfo)) is not None and taken >= deadline
        for path in copies(directory)
    )


def stamp(path: Path, tz: tzinfo | None) -> datetime | None:
    """Время снятия по имени файла.

    Имя пишется в часовом поясе клуба (см. `filename`), в нём же и читается:
    в контейнере системный пояс — UTC, и «04:00» из имени иначе съехало бы
    на три часа.
    """
    raw = path.name.removeprefix(PREFIX).removesuffix(SUFFIX)[:13]
    try:
        return datetime.strptime(raw, "%Y%m%d-%H%M").replace(tzinfo=tz)
    except ValueError:
        return None


def filename(now: datetime) -> str:
    return f"{PREFIX}{now:%Y%m%d-%H%M}{SUFFIX}"


async def dump(database_url: str) -> bytes:
    """Снимает дамп и сжимает его. Пароль уходит через окружение, а не в
    аргументах: аргументы видны любому, кто посмотрит список процессов."""
    url = make_url(database_url)
    process = await asyncio.create_subprocess_exec(
        "pg_dump",
        "-h",
        url.host or "localhost",
        "-p",
        str(url.port or 5432),
        "-U",
        url.username or "postgres",
        "-d",
        url.database or "postgres",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PGPASSWORD": url.password or ""},
    )
    try:
        out, err = await process.communicate()
    except BaseException:
        # Таймаут снаружи отменяет ожидание, но не сам pg_dump — без этого
        # он остался бы висеть сиротой и держать соединение с базой.
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        raise
    if process.returncode != 0:
        raise BackupError(err.decode(errors="replace").strip()[-500:] or "pg_dump упал молча")
    # Сжатие — чистый процессор: в общем цикле бота оно на секунду
    # остановило бы и рассылку, и ответы на кнопки.
    return await asyncio.to_thread(gzip.compress, out, 6)


def save(directory: Path, name: str, data: bytes) -> Path:
    """Пишет через временный файл: оборванная запись не должна выглядеть
    как готовая копия, иначе `is_due` решит, что копия за сегодня есть."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(data)
    partial.replace(target)
    return target


def rotate(directory: Path, keep: int = KEEP) -> list[Path]:
    """Удаляет всё, кроме `keep` самых свежих копий. Возвращает удалённые."""
    old = copies(directory)[:-keep] if keep > 0 else copies(directory)
    for path in old:
        path.unlink(missing_ok=True)
    return old
