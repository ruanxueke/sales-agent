#!/usr/bin/env bash
# 企业微信接入轮次：验证通道状态
set -uo pipefail
cd /opt/sales-agent
API_KEY=$(grep '^API_KEYS=' /opt/sales-agent/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | xargs)
BASE="${1:-http://127.0.0.1:5010}"

for p in "/health" "/api/v1/wecom/status" "/api/v1/channels/overview"; do
  echo "==> $p"
  curl -s -w "\nHTTP:%{http_code}\n" --http1.1 -H "X-API-Key: $API_KEY" "$BASE$p" | head -c 800
  echo ""
done
