#!/usr/bin/env bash
# 销售智能体：部署个人微信客户接待链路与前端状态页
# 用法：
#   1. 上传并解压更新包到 /opt/sales-agent/releases/personal-wechat-flow-20260911
#   2. 执行：
#      bash /opt/sales-agent/deploy/install_personal_wechat_flow_20260911.sh \
#        /opt/sales-agent/releases/personal-wechat-flow-20260911
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/releases/personal-wechat-flow-20260911}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/personal-wechat-flow-$TS"

FILES=(
  "api_server.py"
  "api/personal_wechat.py"
  "core/personal_wechat.py"
  "core/models.py"
  "core/commercial.py"
  "core/db.py"
  "core/llm_router.py"
  "static/console.html"
)

if [ ! -d "$PKG_DIR" ]; then
  echo "更新包目录不存在：$PKG_DIR"
  exit 1
fi

cd "$APP_DIR"
mkdir -p "$BACKUP_DIR"

echo "==> 备份当前文件"
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$f")"
    cp -a "$f" "$BACKUP_DIR/$f"
  fi
done

echo "==> 覆盖个人微信链路文件"
for f in "${FILES[@]}"; do
  if [ ! -f "$PKG_DIR/$f" ]; then
    echo "更新包缺少文件：$f"
    exit 1
  fi
  mkdir -p "$(dirname "$f")"
  cp -f "$PKG_DIR/$f" "$f"
  echo "copied $f"
done

echo "==> 重建并启动容器"
docker compose up -d --build
sleep 12

echo "==> 健康检查"
curl -fsS http://127.0.0.1:5010/health
echo

API_KEY="${API_KEY:-}"
if [ -z "$API_KEY" ] && [ -f .env ]; then
  API_KEY="$(grep '^API_KEYS=' .env | head -n 1 | cut -d= -f2- | cut -d, -f1)"
fi

echo "==> 状态接口检查"
STATUS_CODE="$(curl -sS -o /tmp/personal-wechat-status.json -w '%{http_code}' \
  -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:5010/api/v1/personal-wechat/status")"
cat /tmp/personal-wechat-status.json
echo

if [ "$STATUS_CODE" != "200" ]; then
  echo "状态接口验证失败，HTTP=$STATUS_CODE"
  exit 1
fi

echo "==> 前端页面检查"
curl -fsS http://127.0.0.1:5010/static/console.html | grep -q "客户接待链路"
echo "客户接待链路页面已生效"

echo "==> 部署完成"
echo "回滚文件备份：$BACKUP_DIR"
