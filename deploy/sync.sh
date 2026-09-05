#!/usr/bin/env bash
# Заливка кода с рабочей машины на сервер. Запускать локально, из корня проекта:
#
#   deploy/sync.sh root@1.2.3.4
#
# Репозиторий на сервере не нужен — просто копия файлов.

set -euo pipefail

TARGET="${1:-}"
APP_DIR="${APP_DIR:-cinema-club}"

if [ -z "$TARGET" ]; then
  echo "Укажите сервер: $0 root@адрес" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Исключения критичны: .env на сервере свой (там пароль базы, сгенерированный
# при установке), а venv и node_modules собраны под другую платформу.
rsync -az --delete \
  --exclude '.git' \
  --exclude '.env' \
  --exclude '.db_password' \
  --exclude '.pgdata' \
  --exclude 'backend/venv' \
  --exclude 'backend/__pycache__' \
  --exclude '**/__pycache__' \
  --exclude 'miniapp/node_modules' \
  --exclude "miniapp/dist" \
  "$ROOT/" "$TARGET:$APP_DIR/"

echo "Код залит в $TARGET:$APP_DIR"
echo "Дальше на сервере:  cd ~/cinema-club && sudo docker compose -f docker-compose.prod.yml up -d --build"
