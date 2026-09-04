#!/usr/bin/env bash
# HTTPS-туннель к dev-серверу Mini App, с автоматическим переподключением.
#
# Telegram не принимает localhost и http, поэтому в разработке приложение должно
# светиться наружу по HTTPS. Бесплатный туннель живёт около часа и каждый раз
# выдаёт новый адрес — скрипт поднимает его заново и записывает адрес в .env.
#
# Править BotFather при этом не нужно: бот следит за .env и сам переставляет
# кнопку меню через Telegram API (см. watch_miniapp_url в app/bot.py).
# Достаточно, чтобы бот был запущен.
#
# Использование:  scripts/tunnel.sh     (Ctrl+C — остановить)

set -uo pipefail

PORT="${PORT:-5173}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TUNNEL_PID=""
cleanup() {
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
  echo
  echo "Туннель остановлен."
  exit 0
}
trap cleanup INT TERM

attempt=0
while true; do
  attempt=$((attempt + 1))
  LOG="$(mktemp -t cinema-tunnel)"

  ssh -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o ServerAliveInterval=30 \
      -p 443 -R0:localhost:"$PORT" a.pinggy.io > "$LOG" 2>&1 &
  TUNNEL_PID=$!

  URL=""
  for _ in $(seq 1 40); do
    URL=$(grep -oE 'https://[a-z0-9-]+\.free\.pinggy\.net' "$LOG" | head -1)
    [ -n "$URL" ] && break
    kill -0 "$TUNNEL_PID" 2>/dev/null || break
    sleep 1
  done

  if [ -z "$URL" ]; then
    echo "Попытка $attempt: адрес получить не удалось, повтор через 10 с." >&2
    tail -3 "$LOG" >&2
    kill "$TUNNEL_PID" 2>/dev/null
    rm -f "$LOG"
    sleep 10
    continue
  fi

  if [ -f "$ROOT/.env" ]; then
    sed -i '' "s|^MINIAPP_URL=.*|MINIAPP_URL=$URL|" "$ROOT/.env"
  fi

  cat <<INFO

  Адрес Mini App: $URL

  Записан в .env. Бот подхватит его в течение нескольких секунд и сам
  переставит кнопку меню — BotFather трогать не нужно.

  При первом открытии pinggy покажет предупреждение: нажмите «Enter site».

INFO

  # Ждём падения туннеля и поднимаем заново: бесплатный лимит около часа,
  # а вручную перезапускать каждый час — верный способ забыть.
  wait "$TUNNEL_PID"
  rm -f "$LOG"
  echo "Туннель отвалился, переподключаемся…"
  sleep 3
done
