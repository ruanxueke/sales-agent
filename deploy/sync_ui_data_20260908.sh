#!/usr/bin/env bash
# 销售智能体：同步中台前端 + 本地历史数据到服务器
# 用法：
#   1. 上传销售智能体同步包到服务器任意目录，例如 /opt/sales-agent/sync-20260908
#   2. 执行：bash /opt/sales-agent/deploy/sync_ui_data_20260908.sh /opt/sales-agent/sync-20260908
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/sync-20260908}"
TS="$(date +%Y%m%d-%H%M%S)"

if [ ! -d "$PKG_DIR" ]; then
  echo "同步包目录不存在：$PKG_DIR"
  exit 1
fi

cd "$APP_DIR"

echo "==> 备份当前配置和数据"
[ -f .env ] && cp -a .env ".env.bak.$TS"
[ -d data ] && tar -czf "data.bak.$TS.tar.gz" data
[ -d vector_store ] && tar -czf "vector_store.bak.$TS.tar.gz" vector_store

echo "==> 同步中台前端"
for f in console.html solda.js solda-enterprise.js vision_console.html; do
  if [ -f "$PKG_DIR/static/$f" ]; then
    cp -f "$PKG_DIR/static/$f" "static/$f"
    echo "copied static/$f"
  fi
done

echo "==> 同步 P0 后端权限和验收脚本"
for f in api/system_check.py api/platform.py deploy/verify_p0_20260908.sh; do
  if [ -f "$PKG_DIR/$f" ]; then
    mkdir -p "$(dirname "$f")"
    cp -f "$PKG_DIR/$f" "$f"
    echo "copied $f"
  fi
done

echo "==> 同步本地历史数据"
cp -f "$PKG_DIR/data/customers.db" data/customers.db 2>/dev/null || true
cp -f "$PKG_DIR/data/vector_index.json" data/vector_index.json 2>/dev/null || true
cp -f "$PKG_DIR/data/llm_usage.db" data/llm_usage.db 2>/dev/null || true
cp -f "$PKG_DIR/data/metrics.db" data/metrics.db 2>/dev/null || true

mkdir -p data/knowledge_base data/uploads data/object_store data/notifications data/audit vector_store/chroma_db
[ -d "$PKG_DIR/data/knowledge_base" ] && cp -rf "$PKG_DIR/data/knowledge_base/." data/knowledge_base/ || true
[ -d "$PKG_DIR/data/uploads" ] && cp -rf "$PKG_DIR/data/uploads/." data/uploads/ || true
[ -d "$PKG_DIR/data/object_store" ] && cp -rf "$PKG_DIR/data/object_store/." data/object_store/ || true
[ -d "$PKG_DIR/data/notifications" ] && cp -rf "$PKG_DIR/data/notifications/." data/notifications/ || true
[ -d "$PKG_DIR/data/audit" ] && cp -rf "$PKG_DIR/data/audit/." data/audit/ || true
[ -d "$PKG_DIR/vector_store/chroma_db" ] && cp -rf "$PKG_DIR/vector_store/chroma_db/." vector_store/chroma_db/ || true

echo "==> 重建并启动容器"
docker compose up -d --build
sleep 12

echo "==> 迁移 SQLite 历史数据到 PostgreSQL"
docker exec sales-agent-api-1 python deploy/migrate_sqlite_to_pg.py || echo "migrate skipped or failed"

echo "==> 重建知识库索引"
docker exec sales-agent-api-1 python -c "from knowledge.knowledge_manager import KnowledgeManager; print(KnowledgeManager().import_from_directory())" || echo "knowledge rebuild skipped or failed"

echo "==> 验证服务状态"
docker compose ps
curl -s -w "\nHTTP:%{http_code}\n" http://127.0.0.1:5010/health || true

echo "==> 完成，请检查上方输出"
