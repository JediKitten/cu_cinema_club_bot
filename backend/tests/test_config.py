"""Конфигурация: чего приложение не должно прощать в бою.

Ключ подписи сессий по умолчанию лежит в публичном репозитории. Пока он
годится для запуска, забытая переменная окружения — это не «небезопасно», а
«любой выпишет себе токен суперадмина», и заметить это снаружи нельзя.
"""

import pytest

from app.config import Config


def test_insecure_secret_is_fine_in_development():
    """В разработке ключ из коробки не мешает: подделывать некого."""
    config = Config(app_env="dev", secret_key="dev-insecure-key")
    assert not config.is_production


@pytest.mark.parametrize("key", ["", "dev-insecure-key", "change-me-openssl-rand-hex-32"])
def test_production_refuses_to_start_with_a_known_secret(key):
    """Пустой ключ, дефолтный и оставленный из .env.example — одно и то же."""
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Config(app_env="production", secret_key=key)


def test_production_starts_with_its_own_secret():
    config = Config(app_env="production", secret_key="1f3c" * 16)
    assert config.is_production
