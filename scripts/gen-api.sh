#!/usr/bin/env bash
# Типы ответов API для Mini App — из схемы OpenAPI бэкенда.
#
# Раньше miniapp/src/types.ts повторял backend/app/schemas.py руками, и они
# расходились: однажды из ответа пропало поле, которого ждала сборка, и люди
# оказались заперты снаружи. Теперь типы генерируются, а CI проверяет, что
# сгенерированное не отстало от бэкенда.
#
#   scripts/gen-api.sh            # перегенерировать
#   scripts/gen-api.sh --check    # только проверить (для CI)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/backend/venv/bin/python}"
OUT="$ROOT/miniapp/src/api.gen.ts"
# Версия закреплена и ставится мимо package.json: генератор нужен только
# здесь, а в зависимостях он требовал бы TypeScript 5 вместо нашего 6-го.
GENERATOR="openapi-typescript@7.13.0"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

(cd "$ROOT/backend" && "$PYTHON" -c \
  "import json, sys; from app.main import app; json.dump(app.openapi(), sys.stdout, ensure_ascii=False)") \
  > "$tmp/openapi.json"

# --default-non-nullable false: обязательность полей ответа схема бэкенда
# задаёт сама (Schema в schemas.py), а во входящих запросах поле с
# умолчанием и правда можно не присылать.
npx --yes "$GENERATOR" "$tmp/openapi.json" -o "$tmp/api.gen.ts" --default-non-nullable false >/dev/null

{
  echo "// Сгенерировано scripts/gen-api.sh из схемы OpenAPI бэкенда. Руками не править."
  echo "/* eslint-disable */"
  cat "$tmp/api.gen.ts"
} > "$tmp/final.ts"

if [ "${1:-}" = "--check" ]; then
  if ! diff -q "$tmp/final.ts" "$OUT" >/dev/null 2>&1; then
    echo "miniapp/src/api.gen.ts отстал от бэкенда — запустите scripts/gen-api.sh" >&2
    diff -u "$OUT" "$tmp/final.ts" | head -40 >&2 || true
    exit 1
  fi
  echo "api.gen.ts совпадает со схемой бэкенда"
else
  cp "$tmp/final.ts" "$OUT"
  echo "Обновлён miniapp/src/api.gen.ts"
fi
