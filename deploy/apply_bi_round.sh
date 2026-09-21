#!/usr/bin/env bash
# 数据智能轮次：部署企业级 BI 后端 + 前端入口
set -euo pipefail
cd /opt/sales-agent

FILES=(
  "core/business_intelligence.py"
  "core/models.py"
  "api/business_intelligence.py"
  "api_server.py"
  "static/console.html"
)

for f in "${FILES[@]}"; do
  echo "==> docker cp $f"
  docker cp "$f" "sales-agent-api-1:/app/$f"
done

echo "==> restart sales-agent-api-1"
docker restart sales-agent-api-1
sleep 12

echo "==> health"
curl -s -w "\nHTTP:%{http_code}\n" http://127.0.0.1:5010/health || true

echo "==> verify"
bash /opt/sales-agent/deploy/verify_bi_round.sh || true
