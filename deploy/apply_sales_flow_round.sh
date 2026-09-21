#!/usr/bin/env bash
# 销售流程轮次：部署工作流引擎 + 预测管道 + 智能派单
set -euo pipefail
cd /opt/sales-agent

FILES=(
  "core/models.py"
  "core/sales_flow.py"
  "core/sop.py"
  "core/order.py"
  "api/sales_flow.py"
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
bash /opt/sales-agent/deploy/verify_sales_flow_round.sh || true
