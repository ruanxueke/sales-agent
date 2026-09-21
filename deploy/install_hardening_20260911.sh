#!/usr/bin/env bash
# ============================================================================
# 销售客服智能体 —— 20260911 三阶段加固同步脚本
#
# 用法（在服务器上执行）：
#   cd /opt/sales-agent
#   bash deploy/install_hardening_20260911.sh
#
# 本次同步包含的内容（对应 阶段一 / 阶段二 / 阶段三）：
#   阶段一：乱码修复、Celery 重试与去重、凭据即租户、Alembic 迁移链、
#           镜像瘦身（.dockerignore/密钥不外泄）、Redis 拆库 + 加密码 + AOF
#   阶段二：双数据源收敛（sql_compat）、未鉴权面收口、企业微信强制验签、
#           口令 PBKDF2 + 登录锁定迁 Redis、容器非 root / 健康检查、桥接守护
#   阶段三：静默异常收敛（104 处）、LLM 路由状态迁 Redis、导入期 DB 访问改惰性
#
# 幂等：可重复执行。**可回滚**：所有被覆盖的文件与 .env / compose 先备份到
#       /opt/sales-agent-backups/<时间戳>/（刻意放在 /opt/sales-agent 之外，
#       否则备份里那份 .env 会在下次 build 时被 COPY 进镜像）。
#
# 关键设计（为什么这样写）：
#   1) 先备份 .env、docker-compose.yml、data/、vector_store/，再动任何东西。
#   2) .env 只「补缺失项」，绝不覆盖已有值——里面的密钥我看不到也不该猜。
#   3) REDIS_PASSWORD 若在 .env 里缺失就生成一个：compose 里 redis 与所有 app
#      服务共用同一个 ${REDIS_PASSWORD}，两边取值一致才不会「一个要密码一个不带」。
#   4) 必须 docker compose build：本次 Dockerfile 改成非 root + HEALTHCHECK，
#      沿用旧的 docker cp 方式不会生效，而且旧镜像里没有 alembic。
#   5) 迁移在启动前先单独跑一次，失败即中止（fail fast），不让库结构半新不旧。
# ============================================================================
set -euo pipefail

APP_DIR="/opt/sales-agent"
STAMP="$(date +%Y%m%d-%H%M%S)"
# 备份必须放在 build context 之外。放进 /opt/sales-agent 的话，里面那份 .env
# 会在下一次 `docker compose build` 时被 COPY 进镜像 —— dockerignore 的 `*`
# 不跨 `/`，`.env` 规则兜不住子目录。（.dockerignore 里也已显式排除 backups/。）
BK="/opt/sales-agent-backups/$STAMP"
COMPOSE="docker compose"
[ -f "$APP_DIR/docker-compose.yml" ] || { echo "!! 找不到 $APP_DIR/docker-compose.yml"; exit 1; }

say() { echo; echo "===== $* ====="; }

if [ "$(id -u)" != "0" ]; then
  echo "!! 请用 root 执行（需要 chown data/ 与 vector_store/）"
  exit 1
fi
cd "$APP_DIR"

# ---------------------------------------------------------------------------
say "[1/10] 前置检查"
for c in docker; do
  command -v "$c" >/dev/null 2>&1 || { echo "!! 缺少 $c"; exit 1; }
done
$COMPOSE version >/dev/null 2>&1 || { echo "!! docker compose 不可用"; exit 1; }
[ -f "$APP_DIR/.env" ] || { echo "!! 找不到 $APP_DIR/.env（该文件不在同步包里，必须已存在于服务器）"; exit 1; }
echo "docker / compose / .env 就绪"

# ---------------------------------------------------------------------------
say "[2/10] 备份（.env / compose / 数据）"
mkdir -p "$BK"
cp -a "$APP_DIR/.env" "$BK/.env" 2>/dev/null || true
cp -a "$APP_DIR/docker-compose.yml" "$BK/docker-compose.yml" 2>/dev/null || true
[ -f "$APP_DIR/Dockerfile" ] && cp -a "$APP_DIR/Dockerfile" "$BK/Dockerfile" || true
mkdir -p "$BK/data" "$BK/vector_store"
cp -a "$APP_DIR/data/." "$BK/data/" 2>/dev/null || true
cp -a "$APP_DIR/vector_store/." "$BK/vector_store/" 2>/dev/null || true
echo "备份目录: $BK"
echo "数据库另存一份 pg_dump（失败不阻断，data/ 里已有 sqlite 备份）..."
$COMPOSE exec -T postgres pg_dump -U sales sales > "$BK/postgres.sql" 2>/dev/null \
  && echo "pg_dump 完成: $BK/postgres.sql" \
  || echo "!! pg_dump 跳过（postgres 容器没起或还没就绪），data/ 备份仍可用"

# ---------------------------------------------------------------------------
say "[3/10] 校对 .env（只补缺失项，不覆盖已有值）"
cp -a "$APP_DIR/.env" "$BK/.env.before-quality-fix"
python3 - "$APP_DIR/.env" <<'PY'
import re, secrets, sys

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    lines = f.read().splitlines()

have = {}
for line in lines:
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
    if m and not line.lstrip().startswith("#"):
        have[m.group(1)] = True

# docker compose 强制要求这几项由 .env 提供一致取值。
# 注意：REDIS_URL / CELERY_* 在 compose 的 environment: 里是按 ${REDIS_PASSWORD}
# 现算的，会覆盖 .env 里的同名项，所以这里不必改它们。
add = []
if "REDIS_PASSWORD" not in have:
    add.append(("REDIS_PASSWORD", secrets.token_urlsafe(24)))
if "PG_PASSWORD" not in have:
    add.append(("PG_PASSWORD", secrets.token_urlsafe(24)))
if "APP_UID" not in have:
    add.append(("APP_UID", "1000"))
if "APP_GID" not in have:
    add.append(("APP_GID", "1000"))
# 明文回调默认拒绝：企业微信明文模式不带签名，任何人都能伪造客户消息直达 Agent
if "WECOM_ALLOW_PLAINTEXT_CALLBACK" not in have:
    add.append(("WECOM_ALLOW_PLAINTEXT_CALLBACK", "false"))
# 表结构归迁移链管，禁止 create_all 兜底（否则新增字段线上静默失效）
if "AUTO_CREATE_TABLES" not in have:
    add.append(("AUTO_CREATE_TABLES", "false"))

if not add:
    print("   .env 已包含全部必需项，未改动")
    sys.exit(0)

with open(path, "a", encoding="utf-8") as f:
    f.write("\n\n# --- 20260911 加固同步自动补齐（此前缺失）---\n")
    for k, v in add:
        f.write("%s=%s\n" % (k, v))
        shown = v if k in ("APP_UID", "APP_GID") else "******"
        print("   + %s=%s" % (k, shown))
PY

# ---------------------------------------------------------------------------
say "[4/10] 数据目录属主（容器改非 root 后必须一致）"
APP_UID="$(sed -n 's/^APP_UID=//p' .env | tail -n1)"; APP_UID="${APP_UID:-1000}"
APP_GID="$(sed -n 's/^APP_GID=//p' .env | tail -n1)"; APP_GID="${APP_GID:-1000}"
mkdir -p data vector_store
if chown -R "$APP_UID:$APP_GID" data vector_store 2>/dev/null; then
  echo "data/ 与 vector_store/ 属主 -> $APP_UID:$APP_GID"
else
  echo "!! chown 失败：容器以非 root 运行时会写不进 data/"
  echo "   请手工执行: chown -R $APP_UID:$APP_GID /opt/sales-agent/data /opt/sales-agent/vector_store"
  exit 1
fi

# ---------------------------------------------------------------------------
say "[5/10] 构建镜像（本次必须重建：非 root + HEALTHCHECK + 补 alembic 依赖）"
# 构建期间服务照常跑，先不制造停机。
$COMPOSE build

# ---------------------------------------------------------------------------
say "[6/10] 进入停机窗口：停应用容器，再切基础设施"
# 顺序很重要：redis 这次要加 --requirepass，如果让旧 api/worker 继续跑着去连
# 一个已要求密码的 redis，就会在迁移期间产生一堆鉴权失败（锁与去重键全失效，
# 极端情况下重复回复）。与其半死不活，不如明确停一下。
$COMPOSE stop api official worker beat || true
$COMPOSE up -d postgres redis redis-cache
echo "等待基础设施健康检查..."
wait_healthy() {
  local s st ok i
  for i in $(seq 1 "${2:-40}"); do
    ok=1
    for s in $1; do
      st="$($COMPOSE ps --format '{{.Service}} {{.Health}}' 2>/dev/null | awk -v s="$s" '$1==s{print $2}')"
      [ "$st" = "healthy" ] || ok=0
    done
    [ "$ok" = "1" ] && return 0
    sleep 3
  done
  return 1
}
wait_healthy "postgres redis redis-cache" 60 || echo "!! 基础设施未在预期时间内全部 healthy，仍继续（migrate 会各自依赖 postgres 健康）"
$COMPOSE ps postgres redis redis-cache

# ---------------------------------------------------------------------------
say "[7/10] 数据库结构升级（失败即中止，不让库结构半新不旧）"
if [ ! -f deploy/migrate.sh ]; then
  echo "!! 缺少 deploy/migrate.sh，无法升级结构，已中止"
  exit 1
fi
if ! $COMPOSE run --rm migrate; then
  echo
  echo "!! 结构升级失败，已中止发布。上方是 alembic 输出。"
  echo "   注意：此时应用容器仍处于停止状态。"
  echo "   先恢复服务："
  echo "     cd $APP_DIR && docker compose up -d"
  echo "   回滚配置："
  echo "     cp -a $BK/docker-compose.yml $APP_DIR/ && cp -a $BK/Dockerfile $APP_DIR/ && cp -a $BK/.env $APP_DIR/"
  exit 1
fi

# ---------------------------------------------------------------------------
say "[8/10] 启动全部服务"
$COMPOSE up -d
echo "等待 api 健康..."
wait_healthy "api" 60 || echo "!! api 未在预期时间内 healthy，请看 docker compose logs api"
$COMPOSE ps

# ---------------------------------------------------------------------------
say "[9/10] 冒烟检查"
FAIL=0
echo "-- /health"
curl -fsS --max-time 10 http://127.0.0.1:5010/health && echo || { echo "   !! /health 不通"; FAIL=1; }
echo "-- /docs 必须已关闭（生产不再暴露接口文档）"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:5010/docs)"
[ "$CODE" = "404" ] && echo "   /docs -> 404 正常" || { echo "   !! /docs 返回 $CODE（期望 404，检查 .env 里的 ENABLE_API_DOCS）"; FAIL=1; }
echo "-- 未带 Key 调业务接口必须 401"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:5010/api/v1/customers)"
[ "$CODE" = "401" ] && echo "   /api/v1/customers -> 401 正常" || { echo "   !! 返回 $CODE（期望 401）"; FAIL=1; }
echo "-- 迁移版本（应已到 0008_shared_module_tables）"
$COMPOSE exec -T postgres psql -U sales -d sales -tAc "select version_num from alembic_version" 2>/dev/null \
  | sed 's/^/   alembic_version = /' || echo "   (读取失败，可忽略)"
echo "-- Redis 必须已开启鉴权"
if $COMPOSE exec -T redis redis-cli ping 2>/dev/null | grep -q "NOAUTH"; then
  echo "   redis 已开启鉴权正常"
else
  echo "   !! redis 未要求密码：检查 .env 里的 REDIS_PASSWORD（compose 与 redis 必须同值）"
  FAIL=1
fi
echo "-- 容器是否以非 root 运行"
$COMPOSE exec -T api id -u 2>/dev/null | sed 's/^/   api uid = /' || true

# ---------------------------------------------------------------------------
say "[10/10] 完成"
cat <<EOF
部署完成。

回滚（如需）：
  cd $APP_DIR
  cp -a $BK/.env .env
  cp -a $BK/docker-compose.yml docker-compose.yml
  docker compose down
  cp -a $BK/data/. data/ && cp -a $BK/vector_store/. vector_store/
  # 数据库回滚（危险，确认后再执行）：
  # docker compose exec -T postgres psql -U sales -d sales < $BK/postgres.sql
  docker compose up -d
备份目录：$BK

注意：
1) data/ 已备份为 $BK/data，vector_store 同理。
2) 本次把容器改成非 root 运行，data/ 属主已同步调整为 $APP_UID:$APP_GID。
3) 上面带 !! 的行就是需要处理的问题。
EOF
if [ "$FAIL" != "0" ]; then
  echo
  echo "!! 冒烟检查有未通过项，请把上面带 !! 的行发回来"
  exit 2
fi
