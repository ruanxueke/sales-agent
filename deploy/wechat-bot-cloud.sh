#!/usr/bin/env bash
# 个人微信机器人上云部署：Node + 依赖 + 常驻 + 开机自启
set -e
cd /opt/sales-agent/wechat-bot

echo "[1/4] 检查 Node.js..."
if ! command -v node >/dev/null 2>&1; then
  echo "安装 Node.js 18..."
  curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
  apt-get install -y nodejs
fi
node -v

echo "[2/4] 安装依赖..."
[ -d node_modules ] || npm install --production

echo "[3/4] 配置机器人（API 指向云服务器）..."
cat > run_cloud.sh <<'EOF'
#!/usr/bin/env bash
export AI_API_URL="${AI_API_URL:-http://127.0.0.1:5010/api/v1/chat}"
export TARGET_ROOM_TOPIC="${TARGET_ROOM_TOPIC:-测试销售智能体}"
export REQUIRE_MENTION="${REQUIRE_MENTION:-false}"
export PERSONAL_AUTO_REPLY="${PERSONAL_AUTO_REPLY:-false}"
exec node bot.cjs
EOF
chmod +x run_cloud.sh

echo "[4/4] 启动并守护（pm2 + 开机自启）..."
if ! command -v pm2 >/dev/null 2>&1; then
  npm install -g pm2
fi
pm2 delete sales-wechat-bot 2>/dev/null || true
pm2 start run_cloud.sh --name sales-wechat-bot
pm2 save
pm2 startup systemd 2>/dev/null | bash || pm2 startup 2>/dev/null | tail -1 || true

echo "============================================"
echo "启动完成，现在扫码登录："
echo "二维码文件：/opt/sales-agent/wechat-bot/qrcode.png"
echo "下载二维码后用手机微信扫码；也可以直接在终端看二维码（XShell/Termius 支持）"
echo "日志查看：pm2 logs sales-wechat-bot"
echo "重启：pm2 restart sales-wechat-bot"
echo "============================================"
pm2 logs sales-wechat-bot --lines 15 --nostream || true
