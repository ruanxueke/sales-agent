#!/usr/bin/env bash
# 全量部署：构建容器 -> 同步代码 -> 重启 -> 健康检查
set -e
cd /opt/sales-agent

echo "[1/5] 构建并启动容器"
docker compose up -d --build 2>/dev/null || docker compose up -d || true

echo "[2/5] 同步代码到 api 容器"
for d in api core connectors config knowledge migrations utils static; do
  if [ -d "/opt/sales-agent/$d" ]; then
    docker cp "/opt/sales-agent/$d" sales-agent-api-1:/app/ || true
  fi
done
docker cp /opt/sales-agent/api_server.py sales-agent-api-1:/app/api_server.py
docker cp /opt/sales-agent/main.py sales-agent-api-1:/app/main.py

echo "[3/5] 同步代码到 official 容器（如存在）"
if docker ps -q -f name=sales-agent-official-1 | grep -q .; then
  for d in api core connectors config knowledge migrations utils static; do
    if [ -d "/opt/sales-agent/$d" ]; then
      docker cp "/opt/sales-agent/$d" sales-agent-official-1:/app/ || true
    fi
  done
  docker cp /opt/sales-agent/api_server.py sales-agent-official-1:/app/api_server.py
  docker cp /opt/sales-agent/main.py sales-agent-official-1:/app/main.py
fi

echo "[4/5] 重启服务"
docker restart sales-agent-api-1 || true
docker restart sales-agent-official-1 || true
sleep 12

echo "[5/5] 健康检查"
curl -s -w "\nHTTP:%{http_code}\n" http://127.0.0.1:5010/health
echo "全量部署完成"
