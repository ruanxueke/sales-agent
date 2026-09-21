#!/usr/bin/env bash
# 商业化核心闭环轮次：验证接口
set -uo pipefail
cd /opt/sales-agent
API_KEY=$(grep '^API_KEYS=' /opt/sales-agent/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | xargs)
BASE="${1:-http://127.0.0.1:5010}"

PATHS=(
  "/api/v1/commercial/channel/sessions"
  "/api/v1/commercial/router/rules"
  "/api/v1/commercial/cdp/rfm"
  "/api/v1/commercial/cdp/tags"
  "/api/v1/commercial/marketing/journeys"
  "/api/v1/commercial/content-safety/rules"
)

fail=0
for p in "${PATHS[@]}"; do
  code=$(curl -s -o /tmp/com_verify.out -w "%{http_code}" --http1.1 -H "X-API-Key: $API_KEY" "$BASE$p")
  if [ "$code" = "200" ]; then
    echo "OK   $code $p"
  else
    echo "FAIL $code $p  $(head -c 120 /tmp/com_verify.out 2>/dev/null)"
    fail=1
  fi
done

code=$(curl -s -o /tmp/com_check.out -w "%{http_code}" --http1.1 -H "X-API-Key: $API_KEY" -X POST "$BASE/api/v1/commercial/content-safety/check" -H "Content-Type: application/json" -d '{"text":"测试内容"}')
echo "OK   $code /api/v1/commercial/content-safety/check"
if [ "$code" != "200" ]; then fail=1; fi

if [ "$fail" = "0" ]; then
  echo ""
  echo "商业化核心闭环验证 OK"
else
  echo ""
  echo "存在失败项，请查看上方 FAIL 行与容器日志"
  exit 1
fi
