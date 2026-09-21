#!/usr/bin/env bash
# 修复 sql_compat PostgreSQL 连接池过小导致 API 子进程启动失败的问题。
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/releases/sql-pool-hotfix-20260911}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/sql-pool-hotfix-$TS"

if [ ! -f "$PKG_DIR/core/sql_compat.py" ]; then
  echo "热补丁缺少 core/sql_compat.py：$PKG_DIR"
  exit 1
fi

cd "$APP_DIR"
mkdir -p "$BACKUP_DIR/core"

if [ -f core/sql_compat.py ]; then
  cp -a core/sql_compat.py "$BACKUP_DIR/core/sql_compat.py"
fi

cp -f "$PKG_DIR/core/sql_compat.py" core/sql_compat.py
python3 -m py_compile core/sql_compat.py

echo "==> 重建应用镜像"
docker compose build api worker official beat

echo "==> 重启应用容器"
docker compose up -d --force-recreate api worker official beat

echo "==> 等待 API"
READY=0
for i in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:5010/health >/tmp/sql-pool-health.json 2>/dev/null; then
    READY=1
    break
  fi
  sleep 2
done

cat /tmp/sql-pool-health.json 2>/dev/null || true
echo

if [ "$READY" != "1" ]; then
  echo "API 仍未恢复，请查看：docker compose logs --tail=200 api"
  exit 1
fi

echo "sql_compat 连接池热修复完成"
echo "备份目录：$BACKUP_DIR"
