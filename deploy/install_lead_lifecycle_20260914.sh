#!/usr/bin/env bash
# 首次私聊先建线索，达到 L3 后升级并关联正式客户。
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/releases/lead-lifecycle-20260914}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/lead-lifecycle-$TS"
FILES=("core/agent.py" "core/lead.py")

if [ ! -d "$PKG_DIR" ]; then
  echo "补丁目录不存在：$PKG_DIR"
  exit 1
fi

cd "$APP_DIR"
mkdir -p "$BACKUP_DIR/core"

for f in "${FILES[@]}"; do
  [ -f "$f" ] && cp -a "$f" "$BACKUP_DIR/$f"
  [ -f "$PKG_DIR/$f" ] || { echo "补丁缺少文件：$f"; exit 1; }
  cp -f "$PKG_DIR/$f" "$f"
  echo "copied $f"
done

docker compose build api worker official beat
docker compose up -d --force-recreate api worker official beat
sleep 15

curl -fsS http://127.0.0.1:5010/health
echo
echo "线索与客户分级逻辑部署完成"
echo "备份目录：$BACKUP_DIR"
