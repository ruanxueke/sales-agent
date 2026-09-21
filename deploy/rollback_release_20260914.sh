#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/sales-agent"
BACKUP_DIR="${1:-}"
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

if [ -z "$BACKUP_DIR" ] || [ ! -d "$BACKUP_DIR" ]; then
  echo "usage: $0 /opt/sales-agent/backups/<release-backup>"
  exit 1
fi

cd "$APP_DIR"
echo "==> restore files"
for f in "${FILES[@]}"; do
  if [ -f "$BACKUP_DIR/$f" ]; then
    mkdir -p "$(dirname "$f")"
    cp -f "$BACKUP_DIR/$f" "$f"
    echo "restored $f"
  fi
done

echo "==> validate and restart"
python3 -m py_compile "${FILES[@]}" 2>/dev/null || true
docker compose build api worker beat official
docker compose up -d --force-recreate api worker beat official

for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:5010/health >/dev/null 2>&1; then
    echo "rollback completed"
    exit 0
  fi
  sleep 2
done

echo "rollback restart failed; inspect docker compose logs --tail=200 api"
exit 1
