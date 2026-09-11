"""Подписанная initData для просмотра Mini App вне Telegram.

Mini App впускает только с подписью, которую выдаёт Telegram, — и правильно:
иначе войти под любым пользователем мог бы кто угодно. Но смотреть свежую
вёрстку в браузере от этого не легче, поэтому здесь та же подпись считается
локально, тем же токеном бота из `.env`.

Это не обход входа: без токена бота подпись не собрать, а токен и так лежит
у владельца клуба. Ключ в том, что подделать её нельзя, не имея токена.

Запуск:  ./venv/bin/python -m app.dev_login --tg-id 555001 --name Зритель
"""

import argparse
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from app.config import get_config


def sign(tg_id: int, name: str, username: str | None = None, token: str | None = None) -> str:
    """Собирает и подписывает initData так же, как это делает Telegram."""
    secret_source = token or get_config().telegram_bot_token
    if not secret_source:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан в .env — подпись собрать нечем")

    user = {"id": tg_id, "first_name": name}
    if username:
        user["username"] = username

    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAA-dev",
        # separators без пробелов: Telegram присылает компактный JSON, а подпись
        # считается по строке — лишний пробел сделал бы её недействительной.
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", secret_source.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def main() -> None:
    parser = argparse.ArgumentParser(description="Подписанная initData для локального просмотра")
    parser.add_argument("--tg-id", type=int, required=True)
    parser.add_argument("--name", default="Просмотр")
    parser.add_argument("--username", default=None)
    args = parser.parse_args()
    print(sign(args.tg_id, args.name, args.username))


if __name__ == "__main__":
    main()
