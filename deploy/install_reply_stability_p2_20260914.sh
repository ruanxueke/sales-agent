#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/releases/reply-stability-p2-20260914}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/reply-stability-p2-$TS"
FILES=(
  "api/personal_wechat.py"
  "api_server.py"
  "core/models.py"
  "core/personal_wechat.py"
  "core/lead.py"
  "core/sales_crm.py"
  "core/sales_crm_sa.py"
  "migrations/versions/0009_personal_wechat_reply_reliability.py"
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

echo "==> database migration"
docker compose build migrate api worker beat official
docker compose run --rm migrate

echo "==> recreate services"
docker compose up -d --force-recreate api worker beat official

echo "==> readiness"
READY=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 3 http://127.0.0.1:5010/ready >/tmp/sales-ready.json 2>/dev/null; then
    READY=1
    break
  fi
  sleep 2
done
cat /tmp/sales-ready.json 2>/dev/null || true
echo

if [ "$READY" != "1" ]; then
  echo "service readiness failed; inspect docker compose logs --tail=200 api"
  echo "rollback: bash deploy/rollback_release_20260914.sh $BACKUP_DIR"
  exit 1
fi

echo "reply stability P2 update completed"
echo "backup: $BACKUP_DIR"
