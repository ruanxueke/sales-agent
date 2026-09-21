#!/usr/bin/env bash
# 视觉执行器轮次部署：解压 zip -> docker cp -> 重启 -> 健康检查
set -e
cd /opt/sales-agent
ZIP="${1:-/enterprise-vision-20260828.zip}"

echo "==> 解压 $ZIP"
unzip -o "$ZIP" -d /opt/sales-agent

echo "==> 同步服务端文件"
for f in core/vision.py api/vision.py config/settings.py api_server.py static/console.html static/vision_console.html; do
  echo "docker cp $f"
  docker cp "/opt/sales-agent/$f" "sales-agent-api-1:/app/$f"
done

echo "==> 重启服务"
docker restart sales-agent-api-1
sleep 12

echo "==> 健康检查"
curl -s -w "\nHTTP:%{http_code}\n" http://127.0.0.1:5010/health
echo "视觉执行器轮次部署完成"
