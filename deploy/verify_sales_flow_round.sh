#!/usr/bin/env bash
# 销售流程轮次：验证工作流 / 预测 / 派单接口
set -uo pipefail
cd /opt/sales-agent
API_KEY=$(grep '^API_KEYS=' /opt/sales-agent/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | xargs)
BASE="${1:-http://127.0.0.1:5010}"

PATHS=(
  "/api/v1/sales-flow/overview"
  "/api/v1/sales-flow/workflows"
  "/api/v1/sales-flow/executions"
  "/api/v1/sales-flow/predictions"
  "/api/v1/sales-flow/dispatch/rules"
  "/api/v1/sales-flow/dispatch/candidates"
  "/api/v1/sales-flow/dispatch/stats"
  "/api/v1/bi/overview?days=7"
  "/api/v1/orders"
)

fail=0
for p in "${PATHS[@]}"; do
  code=$(curl -s -o /tmp/sf_verify.out -w "%{http_code}" --http1.1 -H "X-API-Key: $API_KEY" "$BASE$p")
  if [ "$code" = "200" ]; then
    echo "OK   $code $p"
  else
    echo "FAIL $code $p  $(head -c 120 /tmp/sf_verify.out 2>/dev/null)"
    fail=1
  fi
done

if [ "$fail" = "0" ]; then
  echo ""
  echo "销售流程轮次验证 OK"
else
  echo ""
  echo "存在失败项，请查看上方 FAIL 行与容器日志"
  exit 1
fi
