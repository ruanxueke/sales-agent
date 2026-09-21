#!/usr/bin/env bash
# 视觉执行器轮次验证：状态/心跳/去重/任务/审计/暂停
set -uo pipefail
cd /opt/sales-agent
API_KEY=$(grep '^API_KEYS=' /opt/sales-agent/.env | head -n1 | cut -d= -f2- | tr -d '\r\n' | xargs)
BASE="http://127.0.0.1:5010"
fail=0

req() {
  local m=$1 p=$2 b=${3:-}
  local args=(-s -o /tmp/vision_resp.json -w "%{http_code}" -X "$m" --http1.1 -H "X-API-Key: $API_KEY")
  if [ -n "$b" ]; then
    args+=(-H "Content-Type: application/json" -d "$b")
  fi
  local code
  code=$(curl "${args[@]}" "$BASE$p")
  if [ "$code" = "200" ]; then
    echo "OK   $m $p"
  else
    echo "FAIL $m $p HTTP:$code $(head -c 160 /tmp/vision_resp.json 2>/dev/null)"
    fail=1
  fi
}

req GET /api/v1/vision/status
req POST /api/v1/vision/heartbeat '{"instance_id":"verify-agent","mode":"wecom"}'
req POST /api/v1/vision/audit '{"action":"verify","detail":{"round":"vision"},"instance_id":"verify-agent"}'
req GET /api/v1/vision/audit
req POST /api/v1/vision/mark-seen '{"instance_id":"verify-agent","fingerprint":"verify-fp-001"}'
req POST /api/v1/vision/tasks '{"mode":"wecom","contact":"验证联系人","content":"验证任务","instance_id":"verify-agent"}'
req POST /api/v1/vision/tasks/claim '{"instance_id":"verify-agent","limit":1,"mode":"wecom"}'
req POST /api/v1/vision/tasks/complete '{"task_id":"none","status":"cancelled","note":"verify"}'
req GET /api/v1/vision/tasks
req POST /api/v1/vision/pause '{"paused":false,"instance_id":"verify-agent"}'

if [ "$fail" = "0" ]; then
  echo ""
  echo "视觉执行器轮次验证 OK"
else
  echo ""
  echo "存在失败项，请查看上方 FAIL 行与容器日志"
  exit 1
fi
