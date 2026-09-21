#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/releases/remark-name-sync-20260914}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/remark-name-sync-$TS"
FILES=(
  "api/personal_wechat.py"
  "core/personal_wechat.py"
  "core/lead.py"
  "core/sales_crm.py"
  "core/sales_crm_sa.py"
)

if [ ! -d "$PKG_DIR" ]; then
  echo "update package directory not found: $PKG_DIR"
  exit 1
fi

cd "$APP_DIR"

echo "==> backup"
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$f")"
    cp -a "$f" "$BACKUP_DIR/$f"
  fi
done

echo "==> copy files"
for f in "${FILES[@]}"; do
  if [ ! -f "$PKG_DIR/$f" ]; then
    echo "missing file in package: $f"
    exit 1
  fi
  mkdir -p "$(dirname "$f")"
  cp -f "$PKG_DIR/$f" "$f"
  echo "copied $f"
done

echo "==> syntax check"
python3 -m py_compile "${FILES[@]}"

echo "==> rebuild services"
docker compose build api worker beat official
docker compose up -d --force-recreate api worker beat official

echo "==> wait for API"
READY=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:5010/health >/tmp/sales-health.json 2>/dev/null; then
    READY=1
    break
  fi
  sleep 2
done

cat /tmp/sales-health.json 2>/dev/null || true
echo

if [ "$READY" != "1" ]; then
  echo "API did not recover; inspect: docker compose logs --tail=200 api"
  exit 1
fi

echo "==> remark name sync update completed"
echo "backup: $BACKUP_DIR"
