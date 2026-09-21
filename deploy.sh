#!/usr/bin/env bash
set -e
cd /opt/sales-agent

# API Key 不再硬编码在脚本里（明文进版本库等于泄漏）。
# 优先用环境变量 SALES_API_KEY，其次从 .env 的 API_KEYS 取第一个。
API_KEY="${SALES_API_KEY:-$(sed -n 's/^API_KEYS=//p' /opt/sales-agent/.env 2>/dev/null | head -n1 | cut -d, -f1)}"
if [ -z "$API_KEY" ]; then
  echo "!! 未取到 API Key：请在 .env 配置 API_KEYS，或设置环境变量 SALES_API_KEY"
  exit 1
fi

echo "[1/9] 数据目录属主..."
# 容器以非 root 运行（Dockerfile 里 USER app，默认 uid/gid 1000），而
# data/ 与 vector_store/ 是 bind mount，两边属主必须一致，否则容器会因
# Permission denied 起不来或写不进（表现为客户消息读不到、知识库无法落盘）。
# 幂等；对仍以 root 运行的旧容器无影响，可放心执行。
APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"
mkdir -p /opt/sales-agent/data /opt/sales-agent/vector_store
if chown -R "$APP_UID:$APP_GID" /opt/sales-agent/data /opt/sales-agent/vector_store 2>/dev/null; then
  echo "data/ 与 vector_store/ 属主已设为 $APP_UID:$APP_GID"
else
  echo "!! chown 失败：镜像一旦重建为非 root，容器将无法写 data/，请手工处理"
fi

echo "[2/9] 备份数据..."
BK="/opt/sales-agent/data/backup-$(date +%Y%m%d%H%M%S)"
mkdir -p "$BK"
cp /opt/sales-agent/data/customers.db "$BK/" 2>/dev/null || true
cp /opt/sales-agent/data/vector_index.json "$BK/" 2>/dev/null || true
echo "备份目录: $BK"

echo "[3/9] 清理乱码文件名..."
python3 - <<'PY'
import os
d = "/opt/sales-agent/data/knowledge_base"
removed = 0
for name in os.listdir(d):
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        os.remove(os.path.join(d, name))
        removed += 1
print("已清理乱码文件:", removed)
PY

echo "[4/9] 修复历史数据..."
python3 fix_garbled_data.py

echo "[5/9] 同步产品与支付信息..."
python3 sync_product_info.py
curl -s -X POST -H "X-API-Key: $API_KEY" http://127.0.0.1:5010/api/v1/customers/backfill-display-id >/dev/null || true

echo "[6/9] 更新容器代码..."
for f in api_server.py api/payment.py api/knowledge.py api/system_check.py api/feedback.py api/tracing.py api/security.py api/accounts.py api/performance.py api/approval_rules.py api/service_policies.py api/cpq.py api/ticket.py api/audit.py api/crm.py api/compliance_flow.py config/settings.py config/sales_prompt.txt connectors/wechat_official.py connectors/wecom.py core/agent.py core/backup.py core/feedback.py core/citations.py core/tools.py core/llm.py core/llm_router.py core/llm_trace.py core/models.py core/order.py core/message_splitter.py core/scheduler.py core/security_layers.py core/enterprise.py core/security.py core/vector_store.py core/knowledge_gaps.py core/object_storage.py core/audit.py core/realtime.py core/sales_crm.py core/secrets.py core/compliance_flow.py  api/tenant.py api/billing.py api/analytics.py api/ai_capabilities.py api/webchat.py api/integrations.py api/registration.py core/tenant.py core/billing.py core/analytics.py core/forecast.py core/multimodal.py core/orchestrator.py core/voice_ai.py core/webchat.py core/integrations.py  api/image.py knowledge/knowledge_manager.py; do
  docker cp "/opt/sales-agent/$f" "sales-agent-api-1:/app/$f"
  docker cp "/opt/sales-agent/$f" "sales-agent-official-1:/app/$f"
done

docker cp /opt/sales-agent/api/channels.py sales-agent-api-1:/app/api/channels.py
docker cp /opt/sales-agent/api/channels.py sales-agent-official-1:/app/api/channels.py

# 应用 host-gateway 网络配置（个人微信控制接口）
docker compose up -d --no-recreate 2>/dev/null || true

# 整目录同步：避免容器缺文件（force-recreate 后容器回到镜像代码）
for d in api core connectors config knowledge migrations utils static; do
  docker cp "/opt/sales-agent/$d" "sales-agent-api-1:/app/"
  docker cp "/opt/sales-agent/$d" "sales-agent-official-1:/app/"
done
docker cp /opt/sales-agent/api_server.py sales-agent-api-1:/app/api_server.py
docker cp /opt/sales-agent/api_server.py sales-agent-official-1:/app/api_server.py
docker cp /opt/sales-agent/main.py sales-agent-api-1:/app/main.py
docker cp /opt/sales-agent/main.py sales-agent-official-1:/app/main.py

echo "[7/9] 数据库结构升级..."
# 必须在新代码就位、服务重启之前执行：表结构没跟上就重启，接口会直接 500。
# migrate.sh 会区分「全新空库 / create_all 老库 / 已纳管库」并做结构一致性校验，
# 校验不通过会非 0 退出，从而中断本次发布（fail fast）。
if [ -f /opt/sales-agent/deploy/migrate.sh ]; then
  docker compose run --rm migrate || {
    echo "!! 数据库结构升级失败，已中止发布。请检查上方 alembic 输出。"
    exit 1
  }
else
  echo "!! 缺少 deploy/migrate.sh，无法完成结构升级，已中止发布"
  exit 1
fi

echo "[8/9] 重启服务..."

docker cp /opt/sales-agent/static/console.html sales-agent-api-1:/app/static/console.html
docker cp /opt/sales-agent/static/console.html sales-agent-official-1:/app/static/console.html
docker cp /opt/sales-agent/static/solda.js sales-agent-api-1:/app/static/solda.js
docker cp /opt/sales-agent/static/solda.js sales-agent-official-1:/app/static/solda.js
docker cp /opt/sales-agent/static/solda-enterprise.js sales-agent-api-1:/app/static/solda-enterprise.js
docker cp /opt/sales-agent/static/solda-enterprise.js sales-agent-official-1:/app/static/solda-enterprise.js
docker cp /opt/sales-agent/static/mobile.html sales-agent-api-1:/app/static/mobile.html
docker cp /opt/sales-agent/static/mobile.html sales-agent-official-1:/app/static/mobile.html
docker restart sales-agent-api-1
docker restart sales-agent-official-1
sleep 8

echo "[9/9] 重建知识库..."
curl -s -X POST -H "X-API-Key: $API_KEY" http://127.0.0.1:5010/api/v1/knowledge/rebuild
echo
curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:5010/api/v1/knowledge/stats
echo
echo "部署完成"
echo "提示：本次是 docker cp 方式更新代码，Dockerfile 的容器加固（非 root / HEALTHCHECK）"
echo "      需执行一次 docker compose build && docker compose up -d 才会生效；"
echo "      [1/9] 已提前把 data/ 与 vector_store/ 的属主调好，重建后即可直接写。"
