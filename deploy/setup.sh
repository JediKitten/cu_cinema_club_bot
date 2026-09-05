#!/usr/bin/env bash
# Первичная установка киноклуба на чистый Ubuntu/Debian VPS. Запускать от root.
#
#   sudo DOMAIN=cinema.example.ru deploy/setup.sh
#
# Скрипт идемпотентен: повторный запуск не ломает уже настроенное.
# Код к этому моменту должен лежать в /opt/cinema-club (см. deploy/README.md).

set -euo pipefail

DOMAIN="${DOMAIN:-}"
# Почта нужна Let's Encrypt, чтобы предупредить, если автопродление сломается
# и сертификат пойдёт к истечению. Без неё письма приходить не будут.
EMAIL="${EMAIL:-}"
APP_DIR="${APP_DIR:-/opt/cinema-club}"
APP_USER="${APP_USER:-cinema}"
DB_NAME="${DB_NAME:-cinema}"
DB_USER="${DB_USER:-cinema}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Нужны права root: sudo DOMAIN=... $0" >&2
  exit 1
fi
if [ -z "$DOMAIN" ]; then
  echo "Не задан DOMAIN. Пример: sudo DOMAIN=cinema.example.ru $0" >&2
  exit 1
fi
if [ ! -d "$APP_DIR/backend" ]; then
  echo "В $APP_DIR нет кода. Сначала скопируйте проект — см. deploy/README.md" >&2
  exit 1
fi

echo "==> Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-dev build-essential \
  postgresql postgresql-contrib \
  nginx certbot python3-certbot-nginx \
  curl ca-certificates git

# Node нужен только чтобы собрать фронтенд; в рантайме он не участвует.
if ! command -v node >/dev/null || [ "$(node -v | cut -c2-3)" -lt 20 ]; then
  echo "==> Node.js 20"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi

echo "==> Пользователь $APP_USER"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"

echo "==> База данных"
DB_PASSWORD_FILE="$APP_DIR/.db_password"
if [ ! -f "$DB_PASSWORD_FILE" ]; then
  openssl rand -hex 24 > "$DB_PASSWORD_FILE"
  chmod 600 "$DB_PASSWORD_FILE"
fi
DB_PASSWORD="$(cat "$DB_PASSWORD_FILE")"

sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';"
# Пароль переустанавливаем всегда: он мог смениться между запусками.
sudo -u postgres psql -qc "ALTER ROLE $DB_USER PASSWORD '$DB_PASSWORD';"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
  || sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
sudo -u postgres psql -d "$DB_NAME" -qc "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

echo "==> Конфигурация"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  # Секрет генерируем сами: дефолт из примера в проде — открытая дверь.
  SECRET="$(openssl rand -hex 32)"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" "$APP_DIR/.env"
  echo "   создан $APP_DIR/.env — впишите токены перед запуском"
fi
# Адрес базы и Mini App известны только здесь, поэтому проставляем всегда.
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME|" "$APP_DIR/.env"
sed -i "s|^MINIAPP_URL=.*|MINIAPP_URL=https://$DOMAIN|" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

echo "==> Права"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Python-окружение"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/backend/venv" 2>/dev/null || true
sudo -u "$APP_USER" "$APP_DIR/backend/venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/backend/venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

echo "==> Миграции"
sudo -u "$APP_USER" bash -c "cd $APP_DIR/backend && ./venv/bin/alembic upgrade head"

echo "==> Сборка Mini App"
sudo -u "$APP_USER" bash -c "cd $APP_DIR/miniapp && npm ci --silent && npm run build"

echo "==> systemd"
install -m 644 "$APP_DIR/deploy/cinema-api.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/cinema-bot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cinema-api cinema-bot

echo "==> nginx"
sed "s|DOMAIN_PLACEHOLDER|$DOMAIN|g" "$APP_DIR/deploy/nginx.conf.template" \
  > /etc/nginx/sites-available/cinema-club
ln -sf /etc/nginx/sites-available/cinema-club /etc/nginx/sites-enabled/cinema-club
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "==> Файрвол"
if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null 2>&1 || true
  ufw allow 'Nginx Full' >/dev/null 2>&1 || true
  # Postgres наружу не открываем: API ходит к нему по localhost.
fi

echo "==> TLS"
# Telegram требует валидный сертификат — самоподписанный Mini App не примет.
if [ -n "$EMAIL" ]; then
  CERTBOT_CONTACT=(--email "$EMAIL")
else
  CERTBOT_CONTACT=(--register-unsafely-without-email)
  echo "   EMAIL не задан — уведомления об истечении сертификата приходить не будут"
fi
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
  "${CERTBOT_CONTACT[@]}" --redirect || {
  echo "   certbot не справился. Проверьте, что A-запись $DOMAIN указывает на этот сервер," >&2
  echo "   и повторите: certbot --nginx -d $DOMAIN" >&2
}

cat <<DONE

Готово.

  Адрес:  https://$DOMAIN
  Статус: systemctl status cinema-api cinema-bot
  Логи:   journalctl -u cinema-api -f

Осталось вписать в $APP_DIR/.env токены:
  TELEGRAM_BOT_TOKEN, KINOPOISK_API_TOKEN, BOOTSTRAP_SUPERADMIN_TG_ID
и перезапустить: systemctl restart cinema-api cinema-bot

Каталог наполняется отдельно (обязательно из backend/ — конфиг ищет ../.env):
  sudo -u $APP_USER bash -c "cd $APP_DIR/backend && \\
      ./venv/bin/python -m app.import_top --source kinopoisk --limit 100"

Адрес Mini App в BotFather править не нужно — бот выставит кнопку меню сам.
DONE
