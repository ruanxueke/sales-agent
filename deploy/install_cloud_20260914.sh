#!/usr/bin/env bash
# 销售智能体 2026-09-14 云端更新
# 包含：首聊线索 / L3 升客户 / sql_compat 连接池修复
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/releases/cloud-20260914}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/cloud-20260914-$TS"
FILES=("core/agent.py" "core/lead.py" "core/sql_compat.py")

if [ ! -d "$PKG_DIR" ]; then
  echo "更新包目录不存在：$PKG_DIR"
  exit 1
fi

cd "$APP_DIR"
mkdir -p "$BACKUP_DIR/core"

echo "==> 备份"
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    cp -a "$f" "$BACKUP_DIR/$f"
  fi
done

echo "==> 更新后端文件"
for f in "${FILES[@]}"; do
  if [ ! -f "$PKG_DIR/$f" ]; then
    echo "更新包缺少文件：$f"
    exit 1
  fi
  cp -f "$PKG_DIR/$f" "$f"
  echo "copied $f"
done

echo "==> 语法检查"
python3 -m py_compile "${FILES[@]}"

echo "==> 重建应用容器"
docker compose build api worker official beat
docker compose up -d --force-recreate api worker official beat

echo "==> 等待 API 就绪"
READY=0
for i in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:5010/health >/tmp/sales-health.json 2>/dev/null; then
    READY=1
    break
  fi
  sleep 2
done

cat /tmp/sales-health.json 2>/dev/null || true
echo

if [ "$READY" != "1" ]; then
  echo "API 未在预期时间内恢复，请执行：docker compose logs --tail=200 api"
  exit 1
fi

echo "==> 2026-09-14 云端更新完成"
echo "备份目录：$BACKUP_DIR"
