#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."
echo "===== 启动中台 API 和公众号服务 ====="
sudo docker compose up -d --build
sleep 5

echo "===== 健康检查 ====="
echo -n "中台 API /health: "
curl -s http://127.0.0.1:5000/health
echo
echo -n "公众号服务 /health: "
curl -s http://127.0.0.1:8080/health
echo
echo "===== 启动完成 ====="
