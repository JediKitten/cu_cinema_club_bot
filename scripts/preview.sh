#!/usr/bin/env bash
# Локальный просмотр интерфейса — без сервера и без Telegram.
#
# Зачем: посмотреть новую вёрстку (свою или из пулреквеста) на живых данных,
# ничего не выкладывая. Скрипт распаковывает нужную ревизию в отдельную папку,
# поднимает рядом бэкенд на локальной базе, наполняет её демо-данными и печатает
# ссылки: по одной на каждую роль. Ссылка содержит подписанную initData, ту же
# самую, что выдаёт Telegram, — поэтому приложение впускает как обычно, а
# смотреть можно в любом браузере.
#
# Важно: смотрится именно ревизия, а не рабочая копия — незакоммиченные правки
# в неё не попадут (`git archive` их не видит). Чтобы посмотреть их, запустите
# бэкенд и Vite прямо из рабочего дерева, см. docs/DEVELOPMENT.md.
#
# Использование:
#   scripts/preview.sh                 # последний коммит (HEAD)
#   scripts/preview.sh pr-1            # ветка или любая ревизия
#   scripts/preview.sh pr-1 --no-seed  # не добавлять демо-данные
#
# Ctrl+C останавливает оба сервера.

set -uo pipefail

# Внутри строк переменные пишутся как ${ИМЯ}: bash в UTF-8-локали считает
# байты многоточия или кавычки-ёлочки продолжением имени, и «$PORT…» падает
# с «unbound variable». Скобки ставят границу явно.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF="${1:-HEAD}"
[ "${REF#-}" != "$REF" ] && REF="HEAD"   # первым аргументом сразу флаг

SEED=1
for arg in "$@"; do
  [ "$arg" = "--no-seed" ] && SEED=0
done

API_PORT="${API_PORT:-8011}"
WEB_PORT="${WEB_PORT:-5175}"
PYTHON="$ROOT/backend/venv/bin/python"

cd "$ROOT"

if [ ! -x "$PYTHON" ]; then
  echo "Нет окружения бэкенда: $PYTHON"
  echo "Создайте его:  python3 -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt"
  exit 1
fi

SHA="$(git rev-parse --short "$REF" 2>/dev/null)" || { echo "Не нашёл ревизию «${REF}»"; exit 1; }
WORK="$ROOT/.preview/$SHA"

echo "Ревизия:  $REF ($SHA) — $(git log -1 --format=%s "$REF" | cut -c1-60)"

# Распаковываем копию, а не переключаем ветку: рабочая копия остаётся как была,
# и смотреть чужой пулреквест можно, не прерывая свою работу.
if [ ! -d "$WORK" ]; then
  mkdir -p "$WORK"
  git archive "$REF" | tar -x -C "$WORK"
  echo "Распаковано:  .preview/$SHA"
fi

# Зависимости фронтенда переиспользуем — ставить их заново на каждую ревизию
# долго и незачем.
if [ ! -e "$WORK/miniapp/node_modules" ]; then
  if [ -d "$ROOT/miniapp/node_modules" ]; then
    ln -s "$ROOT/miniapp/node_modules" "$WORK/miniapp/node_modules"
  else
    (cd "$WORK/miniapp" && npm install --silent) || exit 1
  fi
fi

# .env нужен и бэкенду (база, токен), и подписи initData.
[ -f "$ROOT/.env" ] && cp "$ROOT/.env" "$WORK/.env"

API_PID=""
WEB_PID=""
cleanup() {
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null
  echo
  echo "Просмотр остановлен. Папка .preview/$SHA осталась — удалите, если не нужна."
  exit 0
}
trap cleanup INT TERM

echo "Миграции и бэкенд на :${API_PORT}…"
(cd "$WORK/backend" && "$PYTHON" -m alembic upgrade head >/dev/null 2>&1)
(cd "$WORK/backend" && "$PYTHON" -m uvicorn app.main:app --port "$API_PORT" \
  >"$WORK/api.log" 2>&1) &
API_PID=$!

for _ in $(seq 1 40); do
  curl -sf "http://localhost:$API_PORT/docs" >/dev/null 2>&1 && break
  sleep 0.5
done
if ! curl -sf "http://localhost:$API_PORT/docs" >/dev/null 2>&1; then
  echo "Бэкенд не поднялся. Последние строки $WORK/api.log:"
  tail -20 "$WORK/api.log"
  cleanup
fi

# Демо-данные и подпись входа берём из рабочей копии, а не из просматриваемой
# ревизии: это инструменты, и в чужом пулреквесте их может не быть вовсе.
# База у обоих одна и та же, из .env.
if [ "$SEED" = "1" ]; then
  echo "Демо-данные…"
  (cd "$ROOT/backend" && "$PYTHON" -m app.preview_seed 2>&1 | sed 's/^/  /')
fi

echo "Фронтенд на :${WEB_PORT}…"
(cd "$WORK/miniapp" && VITE_API_URL="http://localhost:$API_PORT" \
  npx vite --port "$WEB_PORT" --strictPort >"$WORK/web.log" 2>&1) &
WEB_PID=$!

for _ in $(seq 1 40); do
  curl -sf "http://localhost:$WEB_PORT/" >/dev/null 2>&1 && break
  sleep 0.5
done

link() {  # роль, tg_id, имя
  local init
  init="$(cd "$ROOT/backend" && "$PYTHON" -m app.dev_login --tg-id "$2" --name "$3" 2>/dev/null)"
  if [ -z "$init" ]; then
    echo "  $1: не вышло подписать вход (проверьте TELEGRAM_BOT_TOKEN в .env)"
    return
  fi
  # URL-кодирование самой строки: внутри уже есть & и =, и без этого браузер
  # разобрал бы её как несколько параметров.
  local encoded
  encoded="$("$PYTHON" -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=''))" "$init")"
  # Две строки на роль, а не выравнивание в колонку: printf считает байты,
  # и кириллические подписи разной длины разъезжаются.
  printf '  %s\n    http://localhost:%s/?initData=%s\n' "$1" "${WEB_PORT}" "$encoded"
}

echo
echo "Открывайте в браузере (каждая ссылка — вход своей ролью):"
link "Зритель" 900001 "Зритель Демо"
link "Модератор" 900002 "Модератор Демо"
link "Админ" 900003 "Админ Демо"
link "Главный" 900004 "Главный Демо"
echo
printf '  Лендинг и демо-режим\n    http://localhost:%s/?view=landing\n' "${WEB_PORT}"
echo
echo "Логи: $WORK/api.log, $WORK/web.log"
echo "Ctrl+C — остановить."

wait
