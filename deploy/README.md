# Развёртывание на VPS

Ubuntu 22.04/24.04 или Debian 12, права root, домен с A-записью на сервер.

Telegram требует **валидный** TLS-сертификат: самоподписанный он не примет,
а на голый IP сертификат не выпустить — домен обязателен.

## Первая установка

**1. Направьте домен на сервер.** A-запись `cinema.example.ru → IP`. Проверьте,
что она разошлась, иначе certbot не выпустит сертификат:

```bash
dig +short cinema.example.ru
```

**2. Залейте код** (локально, из корня проекта):

```bash
deploy/sync.sh root@IP-сервера
```

**3. Запустите установку** (на сервере):

```bash
sudo DOMAIN=cinema.example.ru EMAIL=you@example.ru /opt/cinema-club/deploy/setup.sh
```

Скрипт ставит Python, Postgres, nginx, Node; заводит системного пользователя
`cinema`; создаёт базу со случайным паролем; накатывает миграции; собирает
Mini App; поднимает systemd-юниты; настраивает nginx и выпускает сертификат.

**4. Впишите токены** в `/opt/cinema-club/.env`:

```
TELEGRAM_BOT_TOKEN=
KINOPOISK_API_TOKEN=
BOOTSTRAP_SUPERADMIN_TG_ID=
```

`DATABASE_URL`, `MINIAPP_URL` и `SECRET_KEY` скрипт проставил сам — их не трогайте.

```bash
sudo systemctl restart cinema-api cinema-bot
```

**5. Наполните каталог:**

```bash
sudo -u cinema bash -c "cd /opt/cinema-club/backend && \
    ./venv/bin/python -m app.import_top --source kinopoisk --limit 100"
```

Адрес Mini App в BotFather править не нужно: бот выставит кнопку меню сам,
взяв `MINIAPP_URL` из `.env`.

## Обновление

```bash
deploy/sync.sh root@IP-сервера          # локально
sudo /opt/cinema-club/deploy/update.sh   # на сервере
```

Миграции накатываются до перезапуска API — иначе новый код успел бы обратиться
к колонкам, которых ещё нет.

## Эксплуатация

```bash
systemctl status cinema-api cinema-bot
journalctl -u cinema-api -f
journalctl -u cinema-bot -f
```

Бэкап базы:

```bash
sudo -u postgres pg_dump cinema | gzip > cinema-$(date +%F).sql.gz
```

## Как это устроено

```
        Telegram
           │  HTTPS, валидный сертификат
           ▼
    nginx :443  ──────────────┐
      │                       │
      │ /  → miniapp/dist     │ /api/ → 127.0.0.1:8000
      │   (статика)           ▼
      │                  cinema-api (uvicorn, 2 воркера)
      │                       │
      │                       ▼
      │                  Postgres :5432 (только localhost)
      │                       ▲
      └── cinema-bot ─────────┘
             │
        long polling к Telegram
```

Фронтенд и API живут на одном origin, поэтому фронтенду не нужен ни
`VITE_API_URL`, ни CORS. Наружу открыты только 80 и 443; API и Postgres
слушают localhost.

## Что стоит сделать потом

* **Порт SSH и вход по ключу.** Установка этого не трогает.
* **Автообновление сертификата.** certbot ставит таймер сам, проверить:
  `systemctl list-timers | grep certbot`.
* **Бэкапы по расписанию.** Команда выше в cron, с выгрузкой за пределы сервера.
* **`X-Frame-Options` не ставится намеренно** — Telegram открывает Mini App
  во фрейме, и этот заголовок сломал бы запуск.
