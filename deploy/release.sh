#!/usr/bin/env bash
# Выкат одной командой. Запускать локально, из любого места репозитория:
#
#   deploy/release.sh user@сервер
#   DEPLOY_TARGET=user@сервер deploy/release.sh
#
# Что делает, по порядку, и почему именно так:
#   1. отказывается выкатывать незакоммиченное — иначе в бою оказывается код,
#      которого нет ни в одном коммите, и откатиться к «тому, что было» нельзя;
#   2. снимает дамп базы на сервере — миграция на живых данных необратима;
#   3. заливает код (deploy/sync.sh), собирает образ, потом поднимает —
#      пока идёт сборка, старые контейнеры продолжают отвечать;
#   4. ждёт, пока /health ответит версией этого коммита, и проверяет, что
#      бандл Mini App, на который ссылается страница, действительно отдаётся.
#      Раньше это сверяли глазами — и однажды код на сервере был свежий,
#      а образ старый.

set -euo pipefail

TARGET="${1:-${DEPLOY_TARGET:-}}"
APP_DIR="${APP_DIR:-cinema-club}"
APP_URL="${APP_URL:-https://cinema.cu3rd.ru}"
COMPOSE="docker compose -f docker-compose.prod.yml"
# Сборка с --quiet минутами ничего не пишет, и простаивающее соединение
# рвётся по дороге — сама сборка на сервере при этом идёт дальше, а скрипт
# падает посередине. Пинги держат соединение живым.
SSH=(ssh -o ServerAliveInterval=20 -o ServerAliveCountMax=6)

if [ -z "$TARGET" ]; then
  echo "Укажите сервер: $0 user@адрес (или DEPLOY_TARGET=user@адрес)" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -n "$(git status --porcelain)" ]; then
  echo "Есть незакоммиченные изменения — сначала коммит:" >&2
  git status --short >&2
  exit 1
fi

SHA="$(git rev-parse --short=12 HEAD)"
echo "Выкатываю $SHA: $(git log -1 --format=%s)"

current="$(curl -fsS "$APP_URL/health" 2>/dev/null | sed -nE 's/.*"version":"([^"]*)".*/\1/p' || true)"
if [ "$current" = "$SHA" ] && [ "${FORCE:-}" != "1" ]; then
  echo "В бою уже $SHA — выкатывать нечего (FORCE=1, чтобы пересобрать всё равно)."
  exit 0
fi

echo "→ дамп базы"
DUMP="backups/cinema-$(date +%Y%m%d-%H%M)-before-$SHA.sql.gz"
# shellcheck disable=SC2029 # переменные подставляются здесь намеренно
"${SSH[@]}" "$TARGET" "mkdir -p ~/backups && cd ~/$APP_DIR \
  && $COMPOSE exec -T db pg_dump -U cinema cinema | gzip > ~/$DUMP \
  && gzip -t ~/$DUMP && test \$(stat -c %s ~/$DUMP) -gt 10000"
echo "  ~/$DUMP"

echo "→ код"
"$ROOT/deploy/sync.sh" "$TARGET" >/dev/null

echo "→ сборка и подъём (на сервере, отвязано от ssh)"
# Сборку нельзя держать на ssh-сессии: на этом хосте её рвут посреди
# многоминутной тишины, и вместе с ней умирала сборка — ровно до `up -d`.
# Запускаем через nohup и читаем лог, пока в нём не появится итог.
LOG="cinema-deploy.log"
# shellcheck disable=SC2029
"${SSH[@]}" "$TARGET" "cd ~/$APP_DIR && nohup sh -c 'export GIT_SHA=$SHA; \
  $COMPOSE build --progress plain && $COMPOSE up -d && echo DEPLOY-DONE || echo DEPLOY-FAILED' \
  > ~/$LOG 2>&1 < /dev/null &" || true

outcome=""
for _ in $(seq 1 120); do
  sleep 10
  # shellcheck disable=SC2029
  outcome="$("${SSH[@]}" "$TARGET" "grep -oE 'DEPLOY-(DONE|FAILED)' ~/$LOG | tail -1" 2>/dev/null || true)"
  [ -n "$outcome" ] && break
done
if [ "$outcome" != "DEPLOY-DONE" ]; then
  echo "Сборка не завершилась успешно (${outcome:-нет итога за 20 минут}). Лог: ssh $TARGET 'tail -50 ~/$LOG'" >&2
  exit 1
fi

echo "→ жду, пока ответит новая версия"
for _ in $(seq 1 60); do
  current="$(curl -fsS "$APP_URL/health" 2>/dev/null | sed -nE 's/.*"version":"([^"]*)".*/\1/p' || true)"
  [ "$current" = "$SHA" ] && break
  sleep 2
done
if [ "$current" != "$SHA" ]; then
  echo "За две минуты /health так и не ответил версией $SHA (сейчас: ${current:-нет ответа})." >&2
  echo "Логи: ssh $TARGET 'cd ~/$APP_DIR && $COMPOSE logs --tail 50 api'" >&2
  exit 1
fi

bundle="$(curl -fsS "$APP_URL/" | grep -oE '/assets/index-[^"]+\.js' | head -1)"
if [ -z "$bundle" ] || ! curl -fsS -o /dev/null "$APP_URL$bundle"; then
  echo "Страница ссылается на бандл «${bundle:-?}», но он не отдаётся." >&2
  exit 1
fi

# shellcheck disable=SC2029
"${SSH[@]}" "$TARGET" "cd ~/$APP_DIR && $COMPOSE ps --format '{{.Service}}: {{.Status}}'"
echo "Готово: $SHA в бою, бандл $bundle."
