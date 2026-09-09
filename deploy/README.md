# Развёртывание

Боевая версия: **https://cinema.cu3rd.ru**

Всё приложение живёт в Docker: на хосте не ставится ни Python, ни Node, ни
Postgres. Так и было выбрано — сервер общий, на нём уже работают чужие сервисы,
и трогать системные пакеты ради нас было нельзя.

## Как устроено

```
        Telegram
           │  HTTPS
           ▼
    Caddy на хосте (чужой, 80/443)
           │  reverse_proxy 127.0.0.1:8089
           ▼
    ┌──────────────────────────────┐
    │ api (uvicorn, 2 воркера)     │  отдаёт и /api, и статику Mini App
    │   └── миграции при старте    │
    ├──────────────────────────────┤
    │ bot (aiogram, long polling)  │
    ├──────────────────────────────┤
    │ db (postgres:16, том)        │  наружу не публикуется
    └──────────────────────────────┘
```

Нюансы, которые легко упустить:

* **Порт только 8089.** Caddy проксирует именно его, а 8000 на хосте уже занят
  чужим контейнером.
* **nginx не нужен и вреден** — 80/443 держит Caddy. Статику Mini App отдаёт
  сам FastAPI, поэтому фронтенду не нужны ни `VITE_API_URL`, ни CORS.
* **certbot не нужен** — сертификатом занимается Caddy.
* **Своя база в своём контейнере.** На хосте 5432 занят Postgres чужого проекта;
  складывать данные к соседям нельзя — их `docker compose down -v` унёс бы и наши.
* **Миграции накатывает только `api`**, до запуска uvicorn. Если бы это делал
  и бот, два процесса полезли бы в схему одновременно.

## Обновление

Локально:

```bash
deploy/sync.sh user@сервер
```

На сервере:

```bash
cd ~/cinema-club && sudo docker compose -f docker-compose.prod.yml up -d --build
```

Пересборка занимает около минуты: фронтенд собирается внутри образа.

## Первая установка на другой сервер

Нужен только Docker и обратный прокси, направляющий домен на `127.0.0.1:8089`.

```bash
deploy/sync.sh user@адрес
```

Затем на сервере создать `~/cinema-club/.env` по образцу `.env.example`,
обязательно задав:

```
POSTGRES_PASSWORD=   # openssl rand -hex 24
SECRET_KEY=          # openssl rand -hex 32
MINIAPP_URL=https://ваш-домен
TELEGRAM_BOT_TOKEN=
KINOPOISK_API_TOKEN=
BOOTSTRAP_SUPERADMIN_TG_ID=
```

`DATABASE_URL` из `.env` не используется: compose подставляет адрес контейнера
базы. Дальше:

```bash
sudo docker compose -f docker-compose.prod.yml up -d --build
sudo docker compose -f docker-compose.prod.yml exec api \
    python -m app.import_top --source kinopoisk --limit 100
```

Адрес Mini App в BotFather править не нужно: бот выставляет кнопку меню сам.

## Эксплуатация

```bash
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml logs -f api
sudo docker compose -f docker-compose.prod.yml logs -f bot
```

Бэкап базы:

```bash
sudo docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U cinema cinema | gzip > cinema-$(date +%F).sql.gz
```

Бэкапы по расписанию пока не настроены — стоит завести.
