#!/usr/bin/env bash
# 销售智能体：部署个人微信读取 -> 中台 -> 定向回复任务接口
# 用法：bash deploy/install_personal_wechat_bridge_20260910.sh /path/to/package
set -euo pipefail

APP_DIR="/opt/sales-agent"
PKG_DIR="${1:-$APP_DIR/personal-wechat-bridge-20260910}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/personal-wechat-bridge-$TS"

if [ ! -d "$PKG_DIR" ]; then
  echo "部署包目录不存在：$PKG_DIR"
  exit 1
fi

cd "$APP_DIR"
mkdir -p "$BACKUP_DIR"

echo "==> 备份即将覆盖的文件"
for f in api_server.py api/personal_wechat.py core/personal_wechat.py core/models.py core/commercial.py core/db.py core/llm_router.py; do
  if [ -f "$f" ]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$f")"
    cp -a "$f" "$BACKUP_DIR/$f"
  fi
done

echo "==> 安装个人微信桥接 API"
for f in api_server.py api/personal_wechat.py core/personal_wechat.py core/models.py core/commercial.py core/db.py core/llm_router.py; do
  if [ ! -f "$PKG_DIR/$f" ]; then
    echo "缺少文件：$PKG_DIR/$f"
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

echo "==> 部署完成"
echo "回滚文件备份位于：$BACKUP_DIR"
