#!/usr/bin/env bash
# 销售智能体 2026-09-15 商用化加固升级
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sales-agent}"
PKG_DIR="${1:-$APP_DIR/releases/commercial-hardening-20260915}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/commercial-hardening-$TS"

FILES=(
  "api_server.py"
  "docker-compose.yml"
  ".env.example"
  "requirements.txt"
  "config/settings.py"
  "core/db.py"
  "core/models.py"
  "core/security.py"
  "core/rbac.py"
  "core/tenancy.py"
  "core/tenant_context.py"
  "core/agent.py"
  "core/lead.py"
  "core/reports.py"
  "core/compliance.py"
  "core/compliance_flow.py"
  "core/privacy.py"
  "core/sales_crm_sa.py"
  "core/vector_store.py"
  "core/rag.py"
  "core/knowledge_gaps.py"
  "core/audit.py"
  "core/backup.py"
  "core/tasks.py"
  "core/scheduler.py"
  "knowledge/knowledge_manager.py"
  "connectors/wecom.py"
  "connectors/wechat_official.py"
  "api/accounts.py"
  "api/audit.py"
  "api/chat.py"
  "api/compliance.py"
  "api/compliance_flow.py"
  "api/crm.py"
  "api/export.py"
  "api/image.py"
  "api/knowledge.py"
  "api/lead.py"
  "api/payment.py"
  "api/reports.py"
  "api/system_check.py"
  "migrations/versions/0010_commercial_hardening.py"
  "scripts/quality_gate.py"
  "scripts/verify_release.py"
  "deploy/restore.sh"
)

if [ ! -d "$PKG_DIR" ]; then
  echo "更新包目录不存在：$PKG_DIR"
  exit 1
fi

cd "$APP_DIR"
mkdir -p "$BACKUP_DIR"

echo "==> 备份当前文件"
for file in "${FILES[@]}"; do
  if [ -f "$file" ]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$file")"
    cp -a "$file" "$BACKUP_DIR/$file"
  fi
done

echo "==> 校验更新包"
for file in "${FILES[@]}"; do
  if [ ! -f "$PKG_DIR/$file" ]; then
    echo "更新包缺少文件：$file"
    exit 1
  fi
done

echo "==> 写入更新文件"
for file in "${FILES[@]}"; do
  mkdir -p "$(dirname "$file")"
  cp -f "$PKG_DIR/$file" "$file"
done

echo "==> Python 语法检查"
PY_FILES=()
for file in "${FILES[@]}"; do
  case "$file" in
    *.py) PY_FILES+=("$file") ;;
  esac
done
python3 -m py_compile "${PY_FILES[@]}"

echo "==> 重建并启动服务"
docker compose build api worker official beat migrate
docker compose up -d --force-recreate postgres redis redis-cache migrate api worker official beat

echo "==> 等待数据库迁移和 API 就绪"
READY=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:5010/health >/tmp/sales-health.json 2>/dev/null; then
    READY=1
    break
  fi
  sleep 2
done

cat /tmp/sales-health.json 2>/dev/null || true
echo
if [ "$READY" != "1" ]; then
  echo "API 未在预期时间内恢复，请检查：docker compose logs --tail=200 api migrate"
  exit 1
fi

echo "==> 校验迁移版本"
docker compose exec -T postgres psql -U sales -d sales -tAc \
  "select version_num from alembic_version" | tee /tmp/sales-revision.txt
if ! grep -q "0010_commercial_hardening" /tmp/sales-revision.txt; then
  echo "迁移版本未到 0010_commercial_hardening，发布未完成"
  exit 1
fi

echo "商用化加固升级完成"
echo "回滚文件备份：$BACKUP_DIR"
