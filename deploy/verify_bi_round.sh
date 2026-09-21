#!/usr/bin/env bash
# 数据智能轮次：验证 BI 接口
set -uo pipefail
cd /opt/sales-agent
API_KEY=$(grep '^API_KEYS=' /opt/sales-agent/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | xargs)
BASE="${1:-http://127.0.0.1:5010}"

PATHS=(
  "/api/v1/bi/overview?days=7"
  "/api/v1/bi/funnel?days=30"
  "/api/v1/bi/roi?days=30"
  "/api/v1/bi/trends?days=14"
  "/api/v1/bi/team?days=30"
  "/api/v1/bi/reports/meta"
  "/api/v1/bi/reports"
  "/api/v1/customer-success/overview"
  "/api/v1/orders"
)

fail=0
for p in "${PATHS[@]}"; do
  code=$(curl -s -o /tmp/bi_verify.out -w "%{http_code}" --http1.1 -H "X-API-Key: $API_KEY" "$BASE$p")
  if [ "$code" = "200" ]; then
    echo "OK   $code $p"
  else
    echo "FAIL $code $p  $(head -c 120 /tmp/bi_verify.out 2>/dev/null)"
    fail=1
  fi
done

if [ "$fail" = "0" ]; then
  echo ""
  echo "数据智能轮次验证 OK"
else
  echo ""
  echo "存在失败项，请查看上方 FAIL 行与容器日志"
  exit 1
fi
