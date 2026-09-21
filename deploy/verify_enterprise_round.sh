#!/usr/bin/env bash
# 企业级落实轮次：逐接口验证（管理员 API Key 应全部 200）
set -uo pipefail
cd /opt/sales-agent
API_KEY=$(grep '^API_KEYS=' /opt/sales-agent/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | xargs)
BASE="${1:-http://127.0.0.1:5010}"

PATHS=(
  "/api/v1/orders"
  "/api/v1/payments"
  "/api/v1/after-sales"
  "/api/v1/shipments"
  "/api/v1/invoices"
  "/api/v1/payment-plans"
  "/api/v1/receivables"
  "/api/v1/campaigns"
  "/api/v1/ad-metrics"
  "/api/v1/repurchases"
  "/api/v1/nurture/campaigns"
  "/api/v1/nurture/rules"
  "/api/v1/nurture/events"
  "/api/v1/quality/reports"
  "/api/v1/sop/templates"
  "/api/v1/sop/executions"
  "/api/v1/handovers"
  "/api/v1/ammo/products"
  "/api/v1/ammo/objections"
  "/api/v1/ammo/competitors"
  "/api/v1/ammo/scripts"
  "/api/v1/ammo/cases"
  "/api/v1/winning/differentiators"
  "/api/v1/winning/evidence"
  "/api/v1/winning/tools"
  "/api/v1/customer-success/overview"
  "/api/v1/customer-success/health?tenant_id=1"
  "/api/v1/customer-success/renewal-alerts"
  "/api/v1/webhooks"
  "/api/v1/system/concurrency-check"
)

fail=0
for p in "${PATHS[@]}"; do
  code=$(curl -s -o /tmp/enterprise_verify.out -w "%{http_code}" --http1.1 -H "X-API-Key: $API_KEY" "$BASE$p")
  if [ "$code" = "200" ]; then
    echo "OK   $code $p"
  else
    echo "FAIL $code $p  $(head -c 120 /tmp/enterprise_verify.out 2>/dev/null)"
    fail=1
  fi
done

if [ "$fail" = "0" ]; then
  echo ""
  echo "全部通过：企业级落实轮次验证 OK"
else
  echo ""
  echo "存在失败项，请查看上方 FAIL 行与容器日志"
  exit 1
fi
