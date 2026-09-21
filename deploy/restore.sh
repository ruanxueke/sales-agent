#!/usr/bin/env bash
# 灾备恢复：从最近一次备份恢复本地业务库、租户向量索引和知识文件
set -e
cd /opt/sales-agent

LATEST=$(ls -1t data/backups/backup-* 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  echo "未找到备份，请先执行备份"
  exit 1
fi
echo "使用备份: $LATEST"

docker compose stop api official 2>/dev/null || true
[ -f "$LATEST/customers.db" ] && cp "$LATEST/customers.db" data/customers.db
for vector_file in "$LATEST"/vector_index*.json; do
  [ -f "$vector_file" ] && cp "$vector_file" data/
done
[ -d "$LATEST/knowledge_base" ] && cp -a "$LATEST/knowledge_base/." data/knowledge_base/
if [ -f "$LATEST/postgres.sql" ]; then
  echo "检测到 PostgreSQL 备份，请确认后执行："
  echo "docker compose exec -T postgres psql -U sales -d sales < $LATEST/postgres.sql"
fi
echo "恢复完成，正在启动服务..."
docker compose start api official 2>/dev/null || docker compose up -d
echo "恢复完成"
