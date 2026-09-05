from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Значения из окружения. Это НЕ параметры системы из §13 спека —
    те живут в таблице settings и правятся главным админом через интерфейс."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://cinema:cinema@localhost:5433/cinema"

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    # HTTPS-адрес Mini App. Telegram не принимает http и localhost, поэтому
    # в разработке сюда идёт адрес туннеля.
    miniapp_url: str = ""

    tmdb_api_token: str = ""
    tmdb_language: str = "ru-RU"
    kinopoisk_api_token: str = ""

    secret_key: str = "dev-insecure-key"
    display_timezone: str = "Europe/Moscow"
    bootstrap_superadmin_tg_id: int | None = None

    session_ttl_hours: int = 24 * 30
    # Каталог собранного Mini App. В проде статику отдаёт само приложение,
    # в разработке её отдаёт dev-сервер Vite и каталога здесь нет.
    frontend_dir: str = "../miniapp/dist"

    @field_validator("bootstrap_superadmin_tg_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        # Незаполненная строка в .env — это «не задано», а не ошибка типа.
        return None if isinstance(value, str) and not value.strip() else value


@lru_cache
def get_config() -> Config:
    return Config()
