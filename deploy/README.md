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

Всё ниже — на сервере, из `~/cinema-club`. `docker` требует `sudo`.
Дальше `COMPOSE` = `sudo docker compose -f docker-compose.prod.yml`.

Состояние и логи:

```bash
$COMPOSE ps
$COMPOSE logs -f api        # запросы, миграции при старте
$COMPOSE logs -f bot        # команды, доставка уведомлений, фоновые задачи
$COMPOSE logs --since 1h api | grep -i error
```

Перезапуск одного процесса (без пересборки):

```bash
$COMPOSE restart bot
```

Разовые команды внутри контейнера — так запускается импорт каталога и любая
другая задача:

```bash
$COMPOSE exec api python -m app.import_top --source kinopoisk --list popular --limit 1500
$COMPOSE exec db psql -U cinema -d cinema -c "select count(*) from users"
```

Долгую команду запускайте открепившись от SSH, иначе обрыв связи её убьёт:

```bash
sudo nohup docker compose -f docker-compose.prod.yml exec -T api \
    python -m app.import_top --source kinopoisk --list popular --limit 1500 \
    > /tmp/import.log 2>&1 &
```

### Бэкап и восстановление

```bash
$COMPOSE exec -T db pg_dump -U cinema cinema | gzip > cinema-$(date +%F).sql.gz
```

Восстановление в **чистую** базу (существующие данные снесёт — сначала снимите
свежий дамп):

```bash
gunzip -c cinema-2026-09-11.sql.gz | $COMPOSE exec -T db psql -U cinema -d cinema
```

Бэкапы по расписанию пока не настроены — **это первое, что стоит завести**
новому владельцу: `pg_dump` по крону с выносом копии за пределы сервера.

### Откат неудачного обновления

Образы собираются из кода, поэтому откат — это откат кода:

```bash
cd ~/cinema-club && git log --oneline -5    # если код приехал git'ом
# или заново залить прошлую ревизию локально:
#   git archive <sha> | ssh user@сервер 'tar -x -C ~/cinema-club'
$COMPOSE up -d --build
```

Миграции назад не откатываются автоматически. Если сломала именно миграция:

```bash
$COMPOSE exec api alembic downgrade -1
```

и только потом возвращайте код. Миграции здесь пишутся с рабочим `downgrade()`
именно для этого случая.

### Ротация секретов

`.env` лежит на сервере в `~/cinema-club/.env` и в git не попадает.
После правки — `$COMPOSE up -d` (перечитывается при старте процесса).

* `TELEGRAM_BOT_TOKEN` — при смене токена перестают работать и вход в Mini App
  (подпись `initData` проверяется им), и бот. Меняются вместе.
* `SECRET_KEY` — при смене все выданные сессии становятся недействительными;
  пользователи просто заходят заново.
* `POSTGRES_PASSWORD` — меняется вместе с паролем роли в самой базе, иначе api
  не подключится.

### Что проверить, если «не работает»

| Симптом | Куда смотреть |
|---|---|
| Mini App не открывается | `$COMPOSE ps` — жив ли api; Caddy на хосте проксирует `127.0.0.1:8089` |
| «Не удалось войти» | `TELEGRAM_BOT_TOKEN` в `.env` — тот же бот, что открывает приложение? |
| Бот молчит | `$COMPOSE logs bot`; long polling рвётся при сетевых проблемах и переподключается сам |
| Уведомления не уходят | `select kind, sent_at, failed_reason from notifications order by id desc limit 20` |
| Кнопка Mini App ведёт не туда | `MINIAPP_URL` в `.env`; бот переставляет кнопку сам за секунды |
| Место на диске | `docker system prune -f` уберёт старые образы после пересборок |
