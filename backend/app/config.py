from functools import lru_cache
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ключ по умолчанию лежит в публичном репозитории, и подпись сессий им равносильна
# её отсутствию: зная строку, любой выпишет себе токен суперадмина. Поэтому в бою
# такой ключ — не «небезопасно», а «не запускаться».
INSECURE_SECRET_KEYS = frozenset({"", "dev-insecure-key", "change-me-openssl-rand-hex-32"})


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
    # dev | production. В бою проставляется в docker-compose.prod.yml и включает
    # проверки, которые в разработке только мешали бы.
    app_env: str = "dev"
    display_timezone: str = "Europe/Moscow"
    bootstrap_superadmin_tg_id: int | None = None

    session_ttl_hours: int = 24 * 30
    # Каталог собранного Mini App. В проде статику отдаёт само приложение,
    # в разработке её отдаёт dev-сервер Vite и каталога здесь нет.
    frontend_dir: str = "../miniapp/dist"

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _refuse_insecure_secret_in_production(self) -> "Config":
        if self.is_production and self.secret_key.strip() in INSECURE_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY не задан или оставлен из примера. Сгенерируйте свой "
                "(openssl rand -hex 32) и положите в .env рядом с docker-compose.prod.yml."
            )
        return self

    @field_validator("bootstrap_superadmin_tg_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        # Незаполненная строка в .env — это «не задано», а не ошибка типа.
        return None if isinstance(value, str) and not value.strip() else value


@lru_cache
def get_config() -> Config:
    return Config()
