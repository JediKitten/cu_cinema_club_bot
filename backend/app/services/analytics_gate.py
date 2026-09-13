"""Пароль на выгрузку данных в боте (расширение по просьбе клуба).

Выгрузку заказывают в Telegram, а не в приложении, поэтому обычная проверка
роли тут не работает: у бота нет сессии Mini App, и человек с правами админа
в приложении — не обязательно тот, кто держит телефон. Отдельный пароль решает
и другую задачу: таблицы бывают нужны тем, кому админка не нужна вовсе —
руководству клуба, вузу, — а раздавать ради выгрузки роль админа значит
раздавать заодно отмену показов и правку параметров.

Пароль хранится хешем (PBKDF2-HMAC-SHA256), а не текстом: строку из базы видят
все, у кого есть доступ к дампу, и в проекте, где дампы снимают перед каждым
выкатом, «просто колонка с паролем» — это пароль, опубликованный много раз.

Ключ лежит в таблице settings, но НАМЕРЕННО вне реестра §13: SettingsService
пропускает неизвестные ключи, и хеш не попадает ни в /api/admin/settings,
ни в форму параметров. Секрет, который нельзя случайно показать, — лучше
секрета, который надо не забыть спрятать.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting, User

SETTING_KEY = "analytics_password"

# 600 тысяч итераций — рекомендация OWASP для PBKDF2-SHA256 на 2023 год.
# Проверка идёт раз в полчаса на человека, так что четверть секунды здесь
# никому не мешает, а перебор по украденному дампу замедляет заметно.
ITERATIONS = 600_000
ALGORITHM = "pbkdf2_sha256"

# Короткий пароль перебирается быстрее, чем меняется, поэтому нижняя граница
# есть: без неё «1234» проживёт в клубе год.
MIN_LENGTH = 8

# Сколько живёт разблокировка. Человек редко качает одну таблицу: полчаса
# хватает на всю пачку, а вечером в чужих руках телефон уже ничего не отдаст.
UNLOCK_TTL = timedelta(minutes=30)

# Перебор через Telegram медленный сам по себе, но не бесконечно: пять
# промахов подряд — и полчаса тишины.
MAX_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=30)
# Промахи забываются: три ошибки за месяц не должны складываться в блокировку.
ATTEMPT_WINDOW = timedelta(minutes=30)


class GateError(ValueError):
    pass


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """`pbkdf2_sha256$<итераций>$<соль>$<хеш>` — самодостаточная строка.

    Параметры лежат рядом с хешем, поэтому поднять число итераций можно, не
    ломая уже выданные пароли: старые проверятся по своим, новые — по новым.
    """
    if len(password.strip()) < MIN_LENGTH:
        raise GateError(f"Пароль короче {MIN_LENGTH} символов — так его подберут за вечер")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify(stored: str | None, password: str) -> bool:
    """Сверяет пароль с хешем. Пустой хеш — выгрузка выключена, не «подходит любой»."""
    if not stored or not password:
        return False
    try:
        algorithm, raw_iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(raw_iterations)
        )
    except (ValueError, TypeError):
        # Мусор в базе значит «пароль не задан», а не «пускать всех».
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


async def stored_hash(session: AsyncSession) -> str | None:
    value = await session.scalar(sa.select(Setting.value).where(Setting.key == SETTING_KEY))
    return value if isinstance(value, str) and value else None


async def is_set(session: AsyncSession) -> bool:
    return await stored_hash(session) is not None


@dataclass(frozen=True, slots=True)
class State:
    """Что показать админу: сам пароль не покажешь, а «кто и когда его менял» —
    единственный способ понять, не пора ли."""

    is_set: bool
    updated_at: datetime | None = None
    updated_by: str | None = None


async def state(session: AsyncSession) -> State:
    row = (
        await session.execute(
            sa.select(Setting.value, Setting.updated_at, User.display_name)
            .outerjoin(User, User.id == Setting.updated_by)
            .where(Setting.key == SETTING_KEY)
        )
    ).first()
    if row is None or not isinstance(row[0], str) or not row[0]:
        return State(is_set=False)
    return State(is_set=True, updated_at=row[1], updated_by=row[2])


async def set_password(session: AsyncSession, password: str, actor_id: int | None) -> None:
    """Пустая строка снимает пароль — и вместе с ним выключает выгрузку."""
    if not password.strip():
        await session.execute(sa.delete(Setting).where(Setting.key == SETTING_KEY))
        return

    stmt = insert(Setting).values(
        key=SETTING_KEY, value=hash_password(password), updated_by=actor_id
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Setting.key],
            set_={
                "value": stmt.excluded.value,
                "updated_by": stmt.excluded.updated_by,
                "updated_at": sa.func.now(),
            },
        )
    )


@dataclass
class AccessGate:
    """Кто уже ввёл пароль и кто промахнулся — в памяти бота.

    В базе этого нет намеренно: состояние живёт полчаса, переживать перезапуск
    ему незачем, а строка «такой-то открыл выгрузку» в таблице — ещё одно
    место, где утекают права. Перезапуск просто просит пароль заново.
    """

    unlocked: dict[int, datetime] = field(default_factory=dict)
    failures: dict[int, list[datetime]] = field(default_factory=dict)

    def unlock(self, tg_id: int, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self.unlocked[tg_id] = now + UNLOCK_TTL
        self.failures.pop(tg_id, None)

    def is_unlocked(self, tg_id: int, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        until = self.unlocked.get(tg_id)
        if until is None:
            return False
        if until <= now:
            del self.unlocked[tg_id]
            return False
        return True

    def lock(self, tg_id: int) -> None:
        self.unlocked.pop(tg_id, None)

    def locked_for(self, tg_id: int, now: datetime | None = None) -> timedelta | None:
        """Сколько ещё ждать после перебора. None — можно пробовать."""
        now = now or datetime.now(UTC)
        recent = self._recent(tg_id, now)
        if len(recent) < MAX_ATTEMPTS:
            return None
        return recent[-1] + LOCKOUT - now

    def register_failure(self, tg_id: int, now: datetime | None = None) -> int:
        """Считает промах и возвращает, сколько попыток осталось."""
        now = now or datetime.now(UTC)
        recent = self._recent(tg_id, now)
        recent.append(now)
        self.failures[tg_id] = recent
        return max(0, MAX_ATTEMPTS - len(recent))

    def _recent(self, tg_id: int, now: datetime) -> list[datetime]:
        window = now - max(ATTEMPT_WINDOW, LOCKOUT)
        return [at for at in self.failures.get(tg_id, ()) if at > window]
