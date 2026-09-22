# Бэкенд

FastAPI + SQLAlchemy 2.0 (async) + Postgres 16, миграции на Alembic, бот на
aiogram 3. Устройство и решения — в [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md),
запуск и грабли — в [../docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md).

## Команды

Все — из этой папки (`backend/`), с локальным окружением `venv`:

```bash
./venv/bin/uvicorn app.main:app --reload --reload-include ../.env   # API на :8000
./venv/bin/python -m app.bot                                        # бот
./venv/bin/alembic upgrade head                                     # схема
./venv/bin/alembic downgrade -1                                     # откатить миграцию
./venv/bin/python -m pytest -q                                      # тесты
./venv/bin/ruff check app tests && ./venv/bin/ruff format app tests # линтер
```

Разовые задачи:

```bash
./venv/bin/python -m app.import_top --source kinopoisk --list popular --limit 1500
./venv/bin/python -m app.preview_seed          # демо-данные для локального просмотра
./venv/bin/python -m app.dev_login --tg-id 900001 --name Зритель
```

## Что где лежит

```
app/
  main.py        сборка приложения, статика Mini App в бою
  bot/           роутеры по темам, рассылка, фоновые циклы, ночные копии, сторож
  config.py      чтение .env
  db.py          движок и сессии
  schemas.py     pydantic-схемы запросов и ответов
  core/
    auth.py           сессии, роли, гейт закрытой беты
    telegram_auth.py  проверка подписи initData
  models/        ORM по темам: catalog, cycle, interest, rating, skip, social, system, user
  api/           роутеры: тонкий слой над сервисами
  services/      вся логика
alembic/versions/  миграции, по файлу на изменение схемы
tests/             pytest, отдельная база cinema_test
```

## Правила, которые держат этот код в порядке

* **Логика — в сервисах.** Роутер переводит HTTP в вызов и ошибку сервиса
  в код ответа; сервис не знает ни про HTTP, ни про Telegram. Благодаря этому
  одно и то же правило работает и в API, и в боте, и в фоновой задаче.
* **Вес отметки не материализован.** Формула §4 — SQL-выражение в
  `services/weights.py`. Не заводите колонку: сломается и песочница §13, и
  пересчёт истории при смене коэффициентов.
* **Enum'ы — `VARCHAR + CHECK`.** Новое значение добавляется миграцией,
  пересобирающей ограничение.
* **Параметры §13 живут в реестре кода** (`services/settings.py`), в базе —
  только переопределения. Новый параметр не требует миграции данных.
* **Уведомления ставятся в очередь, а не отправляются на месте.**
  `notify.queue(...)` + шаблон в `notify.render` — и повторные попытки,
  и идемпотентность по `dedup_key` получаются сами.
* **Ошибки для человека** — своим исключением с русским текстом; роутер
  превращает его в 400/409, а фронтенд показывает как есть.
