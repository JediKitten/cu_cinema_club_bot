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

Одной командой, локально:

```bash
deploy/release.sh user@сервер        # или DEPLOY_TARGET=user@сервер deploy/release.sh
```

Скрипт откажется выкатывать незакоммиченное, снимет дамп базы в
`~/backups/cinema-…-before-<коммит>.sql.gz`, зальёт код, **сначала соберёт
образ, потом поднимет** (пока идёт сборка, старые контейнеры отвечают — простой
в секунды), дождётся, пока `/health` ответит версией этого коммита, и проверит,
что бандл Mini App со страницы действительно отдаётся.

Версия — это коммит, из которого собран образ: её видно в
`curl https://cinema.cu3rd.ru/health`. По ней же Mini App понимает, что сервер
новее, и перезагружается сама — застрять в старой сборке из кэша Telegram
больше нельзя.

Вручную, если скрипт почему-то не подходит, — те же шаги:

```bash
ssh user@сервер 'cd ~/cinema-club && docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U cinema cinema | gzip > ~/backups/cinema-$(date +%Y%m%d-%H%M).sql.gz'
deploy/sync.sh user@сервер
ssh user@сервер 'cd ~/cinema-club && export GIT_SHA=<коммит> \
  && docker compose -f docker-compose.prod.yml build \
  && docker compose -f docker-compose.prod.yml up -d'
```

`sudo` не нужен и мешает: пользователь состоит в группе `docker`, а `sudo`
по ssh без терминала просто падает на запросе пароля.

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
базы. `SECRET_KEY` и `POSTGRES_PASSWORD` обязательны буквально: без них
`docker compose` откажется разворачивать сервисы, а если ключ подписи оставить
из примера, приложение не стартует и скажет почему. Это нарочно — дефолтный
ключ лежит в публичном репозитории, и сессия, подписанная им, равносильна
её отсутствию. Дальше:

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

**Ночные копии снимает бот сам**: раз в сутки после 04:00 по времени клуба —
`pg_dump` в сжатый SQL. Последние 14 копий лежат в томе `backups` (внутри
контейнера бота — `/backups`), а свежая каждую ночь приходит документом
главному админу в Telegram: это копия за пределами сервера. Не снялась — бот
пишет главному админу, почему.

Посмотреть и достать копию с сервера:

```bash
$COMPOSE exec bot ls -lh /backups
$COMPOSE cp bot:/backups/cinema-20260923-0400.sql.gz .
```

Снять копию руками (перед рискованным изменением это делает `release.sh`):

```bash
$COMPOSE exec -T db pg_dump -U cinema cinema | gzip > ~/backups/cinema-$(date +%Y%m%d-%H%M).sql.gz
```

Восстановление в **чистую** базу (существующие данные снесёт — сначала снимите
свежий дамп). Одинаково для ночной копии, ручной и присланной в Telegram:

```bash
gunzip -c cinema-20260923-0400.sql.gz | $COMPOSE exec -T db psql -U cinema -d cinema
```

### Сторож фоновых задач

Бот сам следит за своими циклами (рассылка, задачи клуба, копии базы). Если
какой-то падает три прохода подряд — пишет главному админу текст ошибки.
Если какой-то замолчал совсем (завис так, что не спас и таймаут) — пишет
«перезапускаюсь» и завершает процесс, Docker поднимает его заново. Состояние
видно и в `$COMPOSE ps`: у бота есть healthcheck.

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
