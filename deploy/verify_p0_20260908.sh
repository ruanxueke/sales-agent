#!/usr/bin/env bash
# P0 验收脚本：用于服务器同步后检查核心闭环
set -euo pipefail

BASE="${BASE_URL:-http://127.0.0.1:5010}"
API_KEY="$(grep -E '^API_KEYS=' /opt/sales-agent/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | xargs | cut -d, -f1)"

req() {
  curl -s -m 8 -H "X-API-Key: ${API_KEY}" "$@"
}

fail=0
check() {
  local name="$1"
  local ok="$2"
  local detail="$3"
  if [ "$ok" = "1" ]; then
    echo "PASS $name"
  else
    echo "FAIL $name :: $detail"
    fail=1
  fi
}

health="$(req "${BASE}/health")"
echo "$health" | grep -q '"status":"ok"' && check "health" 1 "$health" || check "health" 0 "$health"

console="$(req "${BASE}/static/console.html")"
echo "$console" | grep -q 'data-view="conversations"' && check "nav-conversations" 1 "" || check "nav-conversations" 0 ""
echo "$console" | grep -q 'data-view="wecom"' && check "nav-wecom" 1 "" || check "nav-wecom" 0 ""
echo "$console" | grep -q 'data-admin-group="true"' && check "nav-system-admin-group" 1 "" || check "nav-system-admin-group" 0 ""

wecom_status="$(req "${BASE}/api/v1/wecom/status")"
check "wecom-status-api" 1 "$wecom_status"

sessions="$(req "${BASE}/api/v1/commercial/channel/sessions?limit=5")"
echo "$sessions" | grep -q '"items"' && check "conversation-sessions" 1 "" || check "conversation-sessions" 0 "$sessions"

metrics="$(req "${BASE}/api/v1/monitor/metrics?window=300")"
echo "$metrics" | grep -q 'total_requests' && check "message-engine-metrics" 1 "" || check "message-engine-metrics" 0 "$metrics"

self_check="$(req "${BASE}/api/v1/system/self-check")"
echo "$self_check" | grep -q '"checks"' && check "system-self-check-admin" 1 "" || check "system-self-check-admin" 0 "$self_check"

roles="$(req "${BASE}/api/v1/roles")"
echo "$roles" | grep -q '"roles"' && check "system-roles-admin" 1 "" || check "system-roles-admin" 0 "$roles"

echo "==========================="
if [ "$fail" = "0" ]; then
  echo "P0 验证全部通过"
else
  echo "P0 验证存在失败项"
  exit 1
fi
