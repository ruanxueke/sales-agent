#!/usr/bin/env bash
# 验证个人微信桥接 API。需要 API_KEY 环境变量。
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5010}"
API_KEY="${API_KEY:-}"

if [ -z "$API_KEY" ]; then
  echo "请先设置 API_KEY"
  exit 1
fi

echo "==> 健康检查"
curl -fsS "$BASE_URL/health"
echo

echo "==> 个人微信任务接口"
HTTP_CODE="$(curl -sS -o /tmp/personal-wechat-tasks.json -w '%{http_code}' \
  -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/personal-wechat/tasks?account_id=verify-account&claim=false&limit=1")"

cat /tmp/personal-wechat-tasks.json
echo

if [ "$HTTP_CODE" != "200" ]; then
  echo "接口验证失败，HTTP=$HTTP_CODE"
  exit 1
fi

echo "个人微信桥接 API 验证通过"
