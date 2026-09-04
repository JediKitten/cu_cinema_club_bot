#!/usr/bin/env bash
# HTTPS-туннель к dev-серверу Mini App.
#
# Telegram не принимает localhost и http, поэтому в разработке приложение
# должно светиться наружу по HTTPS. Скрипт поднимает туннель, вытаскивает
# выданный адрес и подставляет его в .env, чтобы не править файл руками.
#
# Использование:  scripts/tunnel.sh
#
# Бесплатный туннель живёт около часа и при каждом запуске выдаёт новый адрес —
# его нужно вставлять в BotFather (/myapps → Edit Web App URL). При первом
# открытии pinggy показывает страницу-предупреждение: нажать «Enter site»,
# дальше он запоминает согласие в cookie. Обойти её можно только своим
# заголовком запроса, а заголовки запроса Telegram мы не контролируем.
#
# Serveo и localtunnel пробовались и не подошли: у первого такая же заглушка,
# второй терял две трети запросов. Cloudflare Tunnel в этой сети не соединяется.

set -euo pipefail

PORT="${PORT:-5173}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$(mktemp -t cinema-tunnel)"

echo "Поднимаем туннель на порт $PORT…"
ssh -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ServerAliveInterval=30 \
    -p 443 -R0:localhost:"$PORT" a.pinggy.io > "$LOG" 2>&1 &
TUNNEL_PID=$!
# Туннель живёт ровно столько, сколько скрипт: иначе после Ctrl+C остаётся
# осиротевший ssh, который продолжает держать соединение.
trap 'kill $TUNNEL_PID 2>/dev/null || true' EXIT

URL=""
for _ in $(seq 1 40); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.free\.pinggy\.net' "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  kill -0 $TUNNEL_PID 2>/dev/null || { cat "$LOG"; exit 1; }
  sleep 1
done

if [ -z "$URL" ]; then
  echo "Не удалось получить адрес. Вывод туннеля:" >&2
  cat "$LOG" >&2
  exit 1
fi

if [ -f "$ROOT/.env" ]; then
  sed -i '' "s|^MINIAPP_URL=.*|MINIAPP_URL=$URL|" "$ROOT/.env"
  echo "MINIAPP_URL в .env обновлён."
fi

cat <<INFO

  Адрес Mini App: $URL

  1. Вставьте его в BotFather: /myapps → приложение → Edit Web App URL
  2. Откройте приложение и нажмите «Enter site» на странице pinggy

  Туннель работает, пока открыт этот терминал. Ctrl+C — остановить.

INFO

wait $TUNNEL_PID
