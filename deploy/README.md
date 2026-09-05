# Развёртывание

Боевая установка: `cinema.cu3rd.ru`, сервер `87.120.84.226`, пользователь `kir`.

## Схема

```
        Telegram
           │  HTTPS, сертификат Let's Encrypt
           ▼
      Caddy на хосте (:80, :443)     ← чужой, общий для нескольких проектов
           │  reverse_proxy 127.0.0.1:8089
           ▼
    ┌──────────────────────────────────┐
    │ docker compose: cinema-club      │
    │                                  │
    │  api  ── статика + /api ── :8089 │
    │  bot  ── long polling            │
    │  db   ── postgres:16, том db-data│
    └──────────────────────────────────┘
```

Машина общая: на ней живут чужой проект новостей (8 контейнеров), VPN и Caddy.
Отсюда все решения ниже.

**Всё в Docker, на хосте не ставится ничего.** На сервере системный Python 3.8,
а проекту нужен 3.12. Ставить его через PPA на общую машину — лишний риск;
в контейнере вопрос не возникает. Node нужен только для сборки фронтенда и
живёт в первой ступени образа, в рантайм не попадает.

**Своя база в своём контейнере.** На хосте порт 5432 занят Postgres чужого
проекта. Наш `db` наружу не публикуется вовсе — он виден только соседям по сети
compose, и `docker compose down -v` соседей его не заденет.

**Ни nginx, ни certbot.** Порты 80 и 443 держит Caddy, он же терминирует TLS.
Статику Mini App отдаёт само приложение (см. конец `backend/app/main.py`) —
тот же origin, что и API, поэтому фронтенду не нужны ни `VITE_API_URL`, ни CORS.

**Только порт 8089**, привязанный к `127.0.0.1`. Наружу приложение не смотрит.

## Обновление

Локально, из корня проекта:

```bash
deploy/sync.sh kir@87.120.84.226
```

На сервере:

```bash
cd ~/cinema-club
sudo docker compose -f docker-compose.prod.yml up -d --build
```

Миграции накатывает контейнер `api` при старте, до запуска uvicorn — см. его
`command` в compose. Бот их не трогает: иначе два процесса полезли бы в схему
одновременно.

## Первая установка на новую машину

Нужен только Docker и обратный прокси, направленный на `127.0.0.1:8089`.

```bash
deploy/sync.sh kir@адрес
```

На сервере создать `~/cinema-club/.env` из `.env.example` и заполнить:

| Ключ | Откуда |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → /mybots → API Token |
| `KINOPOISK_API_TOKEN` | kinopoisk.dev |
| `BOOTSTRAP_SUPERADMIN_TG_ID` | @userinfobot |
| `MINIAPP_URL` | адрес сайта, например `https://cinema.cu3rd.ru` |
| `SECRET_KEY` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` |

`DATABASE_URL` в `.env` не используется: compose собирает его сам из
`POSTGRES_PASSWORD` и подставляет контейнерам.

```bash
chmod 600 .env
sudo docker compose -f docker-compose.prod.yml up -d --build
sudo docker compose -f docker-compose.prod.yml exec api \
    python -m app.import_top --source kinopoisk --limit 100
```

Адрес Mini App в BotFather выставлять не нужно: бот сам ставит кнопку меню,
взяв `MINIAPP_URL`.

## Эксплуатация

```bash
cd ~/cinema-club
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml logs -f api
sudo docker compose -f docker-compose.prod.yml logs -f bot
```

Контейнеры подняты с `restart: unless-stopped`, а Docker включён в автозагрузку,
поэтому перезагрузку сервера стек переживает сам.

Бэкап базы:

```bash
sudo docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U cinema cinema | gzip > cinema-$(date +%F).sql.gz
```

## Что стоит сделать потом

* **Вход по SSH-ключу** вместо пароля.
* **Бэкапы по расписанию** — команда выше в cron, с выгрузкой за пределы машины.
* **`X-Frame-Options` не выставляется намеренно** — Telegram открывает Mini App
  во фрейме, и этот заголовок сломал бы запуск.
