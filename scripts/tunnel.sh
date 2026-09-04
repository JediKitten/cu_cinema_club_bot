#!/usr/bin/env bash
# HTTPS-туннель к dev-серверу Mini App.
#
# Telegram не принимает localhost и http, поэтому в разработке приложение
# должно светиться наружу по HTTPS. Скрипт поднимает туннель, вытаскивает
# выданный адрес и подставляет его в .env, чтобы не править файл руками.
#
# Использование:
#   scripts/tunnel.sh                 # случайный адрес
#   scripts/tunnel.sh cu-cinema-club  # постоянный, нужен зарегистрированный SSH-ключ
#
# Постоянный поддомен: добавьте свой ключ на https://console.serveo.net/ssh/keys
# Тогда адрес перестанет меняться и BotFather не придётся править при каждом
# перезапуске.

set -euo pipefail

PORT="${PORT:-5173}"
SUBDOMAIN="${1:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$(mktemp -t cinema-tunnel)"

if [ -n "$SUBDOMAIN" ]; then
  FORWARD="$SUBDOMAIN:80:localhost:$PORT"
else
  FORWARD="80:localhost:$PORT"
fi

echo "Поднимаем туннель на порт $PORT…"
ssh -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ServerAliveInterval=30 \
    -o ExitOnForwardFailure=yes \
    -R "$FORWARD" serveo.net > "$LOG" 2>&1 &
TUNNEL_PID=$!
# Туннель живёт ровно столько, сколько скрипт: иначе после Ctrl+C остаётся
# осиротевший ssh, который держит поддомен и мешает переподключиться.
trap 'kill $TUNNEL_PID 2>/dev/null || true' EXIT

URL=""
for _ in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9.-]+\.(serveousercontent\.com|serveo\.net)' "$LOG" | head -1 || true)
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

  Вставьте его в BotFather: /myapps → приложение → Edit Web App URL
  (если адрес не менялся с прошлого раза, шаг можно пропустить)

  Туннель работает, пока открыт этот терминал. Ctrl+C — остановить.

INFO

wait $TUNNEL_PID
