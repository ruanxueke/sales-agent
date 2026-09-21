#!/usr/bin/env bash
# 企业微信接入轮次：部署企微通道代码 + 状态接口
set -euo pipefail
cd /opt/sales-agent

FILES=(
  "connectors/wecom.py"
  "api/channels.py"
  "config/settings.py"
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
bash /opt/sales-agent/deploy/verify_wecom_round.sh || true
