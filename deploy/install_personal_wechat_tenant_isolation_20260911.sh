#!/usr/bin/env bash
# 销售智能体：修复个人微信桥接实例的租户隔离（多用户串台）
#
# 背景：
#   personal_wechat_bridge_instances.instance_id 是全局唯一，
#   而 heartbeat() / update_settings() 早期按 instance_id 单条件查找，没带 tenant_id。
#   结果：多个客户用相同默认 instance_id 时，
#     - A 的心跳会覆盖 B 的实例行（在线状态、账号、错误信息串台）
#     - A 控制台的「开始识别」会真的把 B 的桥接拉起来
#     - B 的 get_settings 读不到自己的行，永远拿默认值（识别永远开不起来）
#
# 用法：
#   1. 上传并解压到 /opt/sales-agent/releases/personal-wechat-tenant-isolation-20260911
#   2. bash /opt/sales-agent/deploy/install_personal_wechat_tenant_isolation_20260911.sh \
#        /opt/sales-agent/releases/personal-wechat-tenant-isolation-20260911
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/releases/personal-wechat-tenant-isolation-20260911}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/personal-wechat-tenant-isolation-$TS"

FILES=(
  "core/personal_wechat.py"
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
    echo "backed up $f"
  fi
done

echo "==> 覆盖租户隔离修复文件"
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

echo "==> 桥接实例接口检查"
STATUS_CODE="$(curl -sS -o /tmp/personal-wechat-status.json -w '%{http_code}' \
  -H "X-API-Key: $API_KEY" \
  "http://127.0.0.1:5010/api/v1/personal-wechat/status")"
cat /tmp/personal-wechat-status.json
echo

if [ "$STATUS_CODE" != "200" ]; then
  echo "状态接口验证失败，HTTP=$STATUS_CODE"
  exit 1
fi

echo "==> 跨租户串台自检（应该被拒绝或互不影响）"
curl -sS -X POST "http://127.0.0.1:5010/api/v1/personal-wechat/bridge/heartbeat" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"instance_id":"tenant-isolation-selftest","account_id":"","status":"offline"}' \
  -o /tmp/personal-wechat-selftest.json -w 'HTTP:%{http_code}\n'
cat /tmp/personal-wechat-selftest.json
echo

echo "==> 部署完成"
echo "回滚文件备份：$BACKUP_DIR"
