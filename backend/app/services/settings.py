"""Параметры системы (§13 спека).

Реестр — единственный источник правды о типах, границах и значениях по умолчанию.
В БД лежат только переопределения, поэтому добавление нового параметра не требует
миграции данных, а забытый в БД ключ автоматически берёт дефолт из кода.
"""

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting

SettingType = Literal["float", "int", "bool", "time", "weekday_time", "str"]


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    type: SettingType
    default: Any
    group: str
    label: str
    min: float | None = None
    max: float | None = None
    help: str | None = None
    # Влияет ли параметр на расчёт весов — при изменении сбрасываем кэш рейтингов.
    affects_weights: bool = False


REGISTRY: tuple[SettingSpec, ...] = (
    # --- Веса ---
    SettingSpec(
        "wishlist_base_weight",
        "float",
        1.0,
        "weights",
        "Базовый вес «Желаемое»",
        0.0,
        100.0,
        affects_weights=True,
    ),
    SettingSpec(
        "wishlist_half_life_days",
        "float",
        180.0,
        "weights",
        "Период полураспада «Желаемого», дней",
        1.0,
        3650.0,
        help="Через столько дней вес отметки падает вдвое.",
        affects_weights=True,
    ),
    SettingSpec(
        "wishlist_weight_floor",
        "float",
        0.2,
        "weights",
        "Нижний порог веса «Желаемого»",
        0.0,
        100.0,
        help="Ниже этого значения вес не опускается, сколько бы ни прошло времени.",
        affects_weights=True,
    ),
    SettingSpec(
        "soon_weight", "float", 3.0, "weights", "Вес «Ближайшее»", 0.0, 100.0, affects_weights=True
    ),
    SettingSpec(
        "soon_ttl_days",
        "int",
        14,
        "weights",
        "Срок жизни «Ближайшего», дней",
        1,
        365,
        affects_weights=True,
    ),
    SettingSpec(
        "soon_limit_per_user", "int", 10, "weights", "Лимит «Ближайших» на пользователя", 1, 1000
    ),
    # --- Зал и явка ---
    SettingSpec("hall_capacity", "int", 40, "hall", "Вместимость зала", 1, 10000),
    SettingSpec(
        "min_attendance",
        "int",
        5,
        "hall",
        "Кворум (минимальная явка)",
        1,
        10000,
        help="Ниже этого числа показ не назначается автопилотом.",
    ),
    SettingSpec(
        "early_warning_hours",
        "int",
        24,
        "hall",
        "За сколько часов предупреждать админов о низкой явке",
        1,
        336,
    ),
    SettingSpec("late_cancel_hours", "int", 24, "hall", "Окно «поздней отмены», часов", 0, 336),
    # --- Цикл ---
    SettingSpec("shortlist_size", "int", 5, "cycle", "Размер шорт-листа", 1, 50),
    SettingSpec(
        "min_weight_threshold",
        "float",
        1.0,
        "cycle",
        "Минимальный вес для автопилота этапа 1",
        0.0,
        1000.0,
    ),
    SettingSpec("long_wait_days", "int", 90, "cycle", "Порог флага «давно ждут», дней", 1, 3650),
    SettingSpec(
        "screening_start_time",
        "time",
        "19:00",
        "cycle",
        "Время начала показа",
        help="Локальное время вуза.",
    ),
    SettingSpec(
        "screening_duration_min", "int", 180, "cycle", "Длительность слота, минут", 30, 600
    ),
    # Дедлайны этапов. Формат «день недели + время» в локальной зоне вуза;
    # 0 = понедельник. Неделя показов начинается в понедельник week_start,
    # все дедлайны относятся к предшествующей ей неделе.
    SettingSpec(
        "stage1_cut_at",
        "weekday_time",
        "2 20:00",
        "cycle",
        "Срез этапа 1",
        help="По умолчанию среда 20:00.",
    ),
    SettingSpec(
        "stage1_autopilot_at",
        "weekday_time",
        "3 08:00",
        "cycle",
        "Автопилот этапа 1",
        help="По умолчанию четверг 08:00.",
    ),
    SettingSpec(
        "shortlist_publish_at", "weekday_time", "3 08:00", "cycle", "Публикация шорт-листа"
    ),
    SettingSpec(
        "stage2_cut_at",
        "weekday_time",
        "5 20:00",
        "cycle",
        "Срез этапа 2",
        help="По умолчанию суббота 20:00.",
    ),
    SettingSpec(
        "stage2_autopilot_at",
        "weekday_time",
        "6 18:00",
        "cycle",
        "Автопилот этапа 2",
        help="По умолчанию воскресенье 18:00.",
    ),
    SettingSpec("schedule_publish_at", "weekday_time", "6 20:00", "cycle", "Публикация расписания"),
    SettingSpec("autopilot_stage1_enabled", "bool", True, "cycle", "Автопилот этапа 1 включён"),
    SettingSpec("autopilot_stage2_enabled", "bool", True, "cycle", "Автопилот этапа 2 включён"),
    # --- Присутствие ---
    SettingSpec(
        "attendance_window_minutes",
        "int",
        20,
        "attendance",
        "Окно отметки присутствия, минут",
        1,
        600,
        help="Отсчитывается от начала сеанса.",
    ),
    SettingSpec(
        "code_rotation_seconds", "int", 60, "attendance", "Период ротации кода, секунд", 10, 3600
    ),
    SettingSpec(
        "feedback_reminder_hours",
        "int",
        24,
        "attendance",
        "Через сколько часов напомнить об оценке",
        1,
        336,
    ),
    # --- Прочее ---
    SettingSpec(
        "beta_invite_required",
        "bool",
        True,
        "misc",
        "Закрытый бета-тест: вход только по коду",
        help="Пока включено, новые участники должны ввести код-приглашение.",
    ),
    SettingSpec("display_timezone", "str", "Europe/Moscow", "misc", "Часовой пояс отображения"),
    SettingSpec(
        "internal_rating_min_votes",
        "int",
        5,
        "misc",
        "Минимум оценок для показа внутреннего рейтинга",
        1,
        1000,
        help="При меньшем числе оценок рейтинг не показывается вовсе (§11).",
    ),
)

BY_KEY: dict[str, SettingSpec] = {s.key: s for s in REGISTRY}

DEFAULTS: dict[str, Any] = {s.key: s.default for s in REGISTRY}


class SettingsError(ValueError):
    pass


def coerce(spec: SettingSpec, raw: Any) -> Any:
    """Приводит значение к типу параметра и проверяет границы."""
    match spec.type:
        case "float":
            value = float(raw)
        case "int":
            value = int(raw)
        case "bool":
            value = raw if isinstance(raw, bool) else str(raw).lower() in {"1", "true", "yes"}
        case "time":
            value = _parse_time(str(raw))
        case "weekday_time":
            value = _parse_weekday_time(str(raw))
        case _:
            value = str(raw)

    if spec.min is not None and isinstance(value, (int, float)) and value < spec.min:
        raise SettingsError(f"{spec.key}: значение {value} меньше минимума {spec.min}")
    if spec.max is not None and isinstance(value, (int, float)) and value > spec.max:
        raise SettingsError(f"{spec.key}: значение {value} больше максимума {spec.max}")
    return value


def _parse_time(raw: str) -> str:
    hh, _, mm = raw.partition(":")
    if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) < 24 and 0 <= int(mm) < 60):
        raise SettingsError(f"Ожидается время в формате ЧЧ:ММ, получено {raw!r}")
    return f"{int(hh):02d}:{int(mm):02d}"


def _parse_weekday_time(raw: str) -> str:
    weekday, _, time_part = raw.strip().partition(" ")
    if not weekday.isdigit() or not 0 <= int(weekday) <= 6:
        raise SettingsError(f"Ожидается «<день 0-6> ЧЧ:ММ» (0 = понедельник), получено {raw!r}")
    return f"{int(weekday)} {_parse_time(time_part)}"


class SettingsService:
    """Читает параметры пачкой. Инстанс живёт в пределах одного запроса,
    поэтому кэш внутри него не может протухнуть на середине расчёта."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cache: dict[str, Any] | None = None

    async def all(self) -> dict[str, Any]:
        if self._cache is None:
            rows = (await self._session.execute(select(Setting))).scalars().all()
            values = dict(DEFAULTS)
            for row in rows:
                if spec := BY_KEY.get(row.key):
                    try:
                        values[row.key] = coerce(spec, row.value)
                    except (SettingsError, TypeError, ValueError):
                        # Мусор в БД не должен ронять приложение — берём дефолт.
                        values[row.key] = spec.default
            self._cache = values
        return self._cache

    async def get(self, key: str) -> Any:
        return (await self.all())[key]

    async def set_many(self, updates: dict[str, Any], actor_id: int | None) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, raw in updates.items():
            spec = BY_KEY.get(key)
            if spec is None:
                raise SettingsError(f"Неизвестный параметр: {key}")
            cleaned[key] = coerce(spec, raw)

        for key, value in cleaned.items():
            stmt = insert(Setting).values(key=key, value=value, updated_by=actor_id)
            await self._session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Setting.key],
                    set_={
                        "value": stmt.excluded.value,
                        "updated_by": stmt.excluded.updated_by,
                        "updated_at": func.now(),
                    },
                )
            )
        self._cache = None
        return cleaned
