#!/usr/bin/env bash
# 云端验证个人微信客户接待链路
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
API_KEY="${API_KEY:-}"

if [ -z "$API_KEY" ]; then
  echo "请设置 API_KEY 后再运行"
  exit 1
fi

echo "==> 服务健康"
curl -fsS "$BASE_URL/health"
echo

echo "==> 链路状态"
curl -fsS \
  -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/personal-wechat/status"
echo

echo "==> 前端页面"
HTTP_CODE="$(curl -sS -o /tmp/sales-console.html -w '%{http_code}' "$BASE_URL/static/console.html")"
grep -q "客户接待链路" /tmp/sales-console.html

if [ "$HTTP_CODE" != "200" ]; then
  echo "前端页面检查失败，HTTP=$HTTP_CODE"
  exit 1
fi

echo "云端个人微信链路与前端页面验证通过"
