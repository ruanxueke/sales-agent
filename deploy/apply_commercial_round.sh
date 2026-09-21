#!/usr/bin/env bash
# 商用化核心闭环轮次：统一会话、路由、CDP/RFM、营销旅程、内容安全
set -euo pipefail
cd /opt/sales-agent

FILES=(
  "core/models.py"
  "core/commercial.py"
  "api/commercial.py"
  "api_server.py"
)

for f in "${FILES[@]}"; do
  echo "==> docker cp $f"
  docker cp "$f" "sales-agent-api-1:/app/$f"
done

echo "==> restart sales-agent-api-1"
docker restart sales-agent-api-1
sleep 15

echo "==> health"
curl -s -w "\nHTTP:%{http_code}\n" http://127.0.0.1:5010/health || true

echo "==> verify"
bash /opt/sales-agent/deploy/verify_commercial_round.sh || true
