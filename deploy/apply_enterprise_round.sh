#!/usr/bin/env bash
# 企业级落实轮次：部署租户隔离 + Webhook 增强 + 客户成功体系
set -euo pipefail
cd /opt/sales-agent

FILES=(
  "api/customer_success.py"
  "api/order.py"
  "api/finance.py"
  "api/marketing.py"
  "api/nurture.py"
  "api/quality.py"
  "api/sop.py"
  "api/handover.py"
  "api/ammo.py"
  "api/winning.py"
  "api/webchat.py"
  "api/concurrency_check.py"
  "core/customer_success.py"
  "core/concurrency_check.py"
  "api_server.py"
)

for f in "${FILES[@]}"; do
  echo "==> docker cp $f"
  docker cp "$f" "sales-agent-api-1:/app/$f"
done

echo "==> restart sales-agent-api-1"
docker restart sales-agent-api-1
sleep 10

echo "==> health"
curl -s -w "\nHTTP:%{http_code}\n" http://127.0.0.1:5010/health || true

echo "==> verify"
bash /opt/sales-agent/deploy/verify_enterprise_round.sh || true
