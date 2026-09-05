#!/usr/bin/env bash
# Обновление уже развёрнутого киноклуба. Запускать от root на сервере:
#
#   sudo deploy/update.sh
#
# Порядок важен: миграции накатываются до перезапуска API, иначе новый код
# успеет обратиться к колонкам, которых ещё нет.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cinema-club}"
APP_USER="${APP_USER:-cinema}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Нужны права root: sudo $0" >&2
  exit 1
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Зависимости backend"
sudo -u "$APP_USER" "$APP_DIR/backend/venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

echo "==> Миграции"
sudo -u "$APP_USER" bash -c "cd $APP_DIR/backend && ./venv/bin/alembic upgrade head"

echo "==> Сборка Mini App"
sudo -u "$APP_USER" bash -c "cd $APP_DIR/miniapp && npm ci --silent && npm run build"

echo "==> Перезапуск"
install -m 644 "$APP_DIR/deploy/cinema-api.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/cinema-bot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl restart cinema-api cinema-bot

sleep 2
if curl -sf -m 10 http://127.0.0.1:8000/health >/dev/null; then
  echo "Готово. API отвечает."
else
  echo "API не отвечает — смотрите: journalctl -u cinema-api -n 50" >&2
  exit 1
fi
