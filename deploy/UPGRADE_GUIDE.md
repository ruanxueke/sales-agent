# 企业级升级部署指南

## 架构变更概览

```
旧架构：                          新架构：
┌──────────┐                     ┌──────────────────────────┐
│  SQLite   │ ← 单文件锁          │  PostgreSQL 16           │ ← 连接池+并发
│  内存缓存  │ ← 进程内            │  Redis 7                 │ ← 缓存/队列/会话
│  单进程    │ ← uvicorn 1 worker  │  uvicorn 2 workers       │ ← 多进程
│  线程调度  │ ← scheduler 跑在API内│  Celery Worker + Beat    │ ← 任务分离
└──────────┘                     └──────────────────────────┘
```

## 部署步骤

### 第 1 步：上传更新包

把 `full-update-patch.zip` 上传到服务器 `/`

### 第 2 步：解压并备份

```bash
# 备份当前数据
cp -r /opt/sales-agent/data /opt/sales-agent/data.bak.$(date +%Y%m%d)
cp /opt/sales-agent/.env /opt/sales-agent/.env.bak

# 解压新代码
unzip -o /full-update-patch.zip -d /tmp/sales-update
cp -r /tmp/sales-update/sales-agent/* /opt/sales-agent/
rm -rf /tmp/sales-update
```

### 第 3 步：配置 .env 新增项

```bash
cat >> /opt/sales-agent/.env << 'EOF'

# === 企业级升级 ===
DATABASE_URL=postgresql://sales:sales2026@postgres:5432/sales
READ_DATABASE_URL=
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
DB_POOL_SIZE=20
DB_READ_POOL_SIZE=30
DB_MAX_OVERFLOW=10
DB_POOL_RECYCLE=3600
UVICORN_WORKERS=2
PG_PASSWORD=sales2026
EOF
```

> **安全提示**：`PG_PASSWORD` 请改成强密码，上面的 `sales2026` 只是示例。

### 第 4 步：启动新架构

```bash
cd /opt/sales-agent

# 停止旧容器
docker compose down

# 重建镜像（安装 psycopg2/redis/celery 等新依赖）
docker compose up -d --build

# 等待 PostgreSQL 健康检查通过
docker compose ps
```

### 第 5 步：迁移 SQLite 数据到 PostgreSQL

```bash
# 在 api 容器内执行迁移脚本
docker exec sales-agent-api-1 python deploy/migrate_sqlite_to_pg.py \
  --sqlite /app/data/customers.db \
  --pg postgresql://sales:sales2026@postgres:5432/sales
```

### 第 6 步：验证

```bash
# 检查所有容器状态
docker compose ps

# 检查数据库连接
docker exec sales-agent-api-1 python -c "
from core.db import check_db_health
import json
print(json.dumps(check_db_health(), indent=2))
"

# 检查 Redis
docker exec sales-agent-redis-1 redis-cli ping

# 检查 Celery Worker
docker logs sales-agent-worker-1 --tail 5

# 检查 API 日志
docker logs sales-agent-api-1 --tail 10

# 测试 API
curl http://localhost:5010/health
```

### 第 7 步：更新 Nginx（可选，负载均衡）

```bash
cp /opt/sales-agent/deploy/nginx-sales-agent.conf /etc/nginx/conf.d/sales-agent.conf
nginx -t && nginx -s reload
```

## 回滚方案

如果新架构出问题，可以快速回滚到 SQLite：

```bash
# 1. 停止新容器
docker compose down

# 2. 恢复 .env（去掉 DATABASE_URL 和 REDIS_URL）
cp /opt/sales-agent/.env.bak /opt/sales-agent/.env

# 3. 恢复旧 docker-compose.yml（从备份或 git）
# 4. 重新启动
docker compose up -d
```

代码会自动降级：
- 无 `DATABASE_URL` → 回退到 SQLite
- 无 `REDIS_URL` → 回退到内存缓存
- 无 `CELERY_BROKER_URL` → 回退到线程调度

## 内存分配（1.6G ECS）

| 组件 | 内存限制 | 说明 |
|------|---------|------|
| PostgreSQL | 256MB | 足够 2000 用户规模 |
| Redis | 128MB | 缓存+队列 |
| API (uvicorn ×2) | 400MB | 双 Worker |
| Celery Worker | 200MB | 2 并发 |
| Celery Beat | 128MB | 定时调度 |
| Official (公众号) | 200MB | 单实例 |
| 系统预留 | ~300MB | OS + Nginx |
| **合计** | **~1.4GB** | **可行** |
