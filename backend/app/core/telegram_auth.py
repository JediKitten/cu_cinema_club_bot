"""Проверка initData Telegram Mini App (§12).

Схема из документации Telegram: секрет — HMAC-SHA256 от токена бота с ключом
"WebAppData", подпись — HMAC-SHA256 от строки проверки с этим секретом.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

MAX_AUTH_AGE_SECONDS = 24 * 3600


class InitDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramUser:
    tg_id: int
    first_name: str
    last_name: str | None
    username: str | None
    photo_url: str | None

    @property
    def display_name(self) -> str:
        return " ".join(filter(None, (self.first_name, self.last_name))) or (
            self.username or f"user{self.tg_id}"
        )


def parse_init_data(
    init_data: str, bot_token: str, *, max_age: int = MAX_AUTH_AGE_SECONDS
) -> TelegramUser:
    if not bot_token:
        raise InitDataError("TELEGRAM_BOT_TOKEN не задан — проверить подпись невозможно")

    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("В initData нет поля hash")

    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("Подпись initData не совпала")

    # Без проверки давности подписанная строка работала бы вечно: перехваченный
    # initData давал бы бессрочный вход.
    auth_date = int(fields.get("auth_date", 0))
    if max_age and (time.time() - auth_date) > max_age:
        raise InitDataError("initData устарел, переоткройте приложение")

    try:
        user = json.loads(fields["user"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise InitDataError("В initData нет корректного поля user") from exc

    return TelegramUser(
        tg_id=int(user["id"]),
        first_name=user.get("first_name", ""),
        last_name=user.get("last_name"),
        username=user.get("username"),
        photo_url=user.get("photo_url"),
    )
