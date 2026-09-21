"""数据库层：SQLAlchemy 引擎与会话，支持 SQLite / PostgreSQL
企业级改造：连接池 + 读写分离 + 慢查询日志
"""
from __future__ import annotations
import logging
import time
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from config.settings import settings
from core import tenant_context  # noqa: F401 - 注册租户 SQLAlchemy 事件

logger = logging.getLogger(__name__)

# init_db() 被大量模块在导入期调用，这里控制提示只输出一次
_init_db_reported = False


class Base(DeclarativeBase):
    pass


# ============================================================
# 引擎构建
# ============================================================

def _build_engine(url: str = "", read_only: bool = False):
    """构建 SQLAlchemy 引擎
    - SQLite：StaticPool（单连接，无排队）
    - PostgreSQL：QueuePool（连接池，支持并发）
    - read_only=True 时可用于只读副本
    """
    if not url:
        url = f"sqlite:///{settings.DATA_DIR / 'customers.db'}"

    kwargs: dict = {"echo": False}

    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        # PostgreSQL / MySQL 连接池配置
        pool_size = getattr(settings, "DB_POOL_SIZE", 20) if not read_only else getattr(settings, "DB_READ_POOL_SIZE", 30)
        kwargs["poolclass"] = QueuePool
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = getattr(settings, "DB_MAX_OVERFLOW", 10)
        kwargs["pool_recycle"] = getattr(settings, "DB_POOL_RECYCLE", 3600)
        kwargs["pool_pre_ping"] = True  # 自动检测断连
        kwargs["pool_timeout"] = 10

    engine = create_engine(url, **kwargs)

    # 慢查询日志（> 500ms）
    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, stmt, params, context, executemany):
        conn.info.setdefault("query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, stmt, params, context, executemany):
        starts = conn.info.get("query_start", [])
        if starts:
            elapsed = (time.perf_counter() - starts.pop()) * 1000
            if elapsed > 500:
                logger.warning("慢查询 %.0fms: %s", elapsed, stmt[:200])

    return engine


# ============================================================
# 主引擎 + 只读引擎
# ============================================================

DATABASE_URL = settings.DATABASE_URL or f"sqlite:///{settings.DATA_DIR / 'customers.db'}"
READ_DATABASE_URL = getattr(settings, "READ_DATABASE_URL", "")

engine = _build_engine(DATABASE_URL)
read_engine = _build_engine(READ_DATABASE_URL or DATABASE_URL, read_only=True) if READ_DATABASE_URL else engine

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
ReadSessionLocal = sessionmaker(bind=read_engine, autoflush=False, expire_on_commit=True)


def schema_revision() -> str:
    """读取当前库的 alembic 版本号；未纳入迁移管理时返回空串。"""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
        return str(row[0]) if row else ""
    except Exception:
        return ""


def init_db() -> None:
    """确保表结构就绪。

    生产环境（AUTO_CREATE_TABLES=false）：本函数不再建表，只校验连通性并提示当前
    迁移版本，表结构由 `alembic upgrade head` 负责（见 deploy/migrate.sh）。
    原因是 `Base.metadata.create_all()` 只创建缺失的表，永远不会修改已存在的表——
    继续依赖它会让「给已有表加字段」在线上静默失效，这正是迁移链长期脱节的根因。

    开发环境（AUTO_CREATE_TABLES=true，默认）：保留 create_all，方便零配置起步。
    """
    import core.models  # noqa: F401

    # 这个函数被 40 多个模块在导入期各调一次，日志只提示一次即可，否则会刷屏
    global _init_db_reported
    first_time = not _init_db_reported
    _init_db_reported = True

    if not getattr(settings, "AUTO_CREATE_TABLES", True):
        if not first_time:
            return
        revision = schema_revision()
        if revision:
            logger.info("已禁用自动建表（AUTO_CREATE_TABLES=false），当前迁移版本：%s", revision)
        else:
            logger.warning(
                "已禁用自动建表（AUTO_CREATE_TABLES=false），但库里没有 alembic_version 表——"
                "表结构尚未纳入迁移管理，请先执行 deploy/migrate.sh（首次会对已有库盖章 0006）"
            )
        return

    if not first_time:
        return

    url = str(engine.url)
    logger.warning(
        "init_db() 正在用 create_all 建表（AUTO_CREATE_TABLES=true，仅适用于开发）；"
        "正式部署请置为 false 并改用 alembic upgrade head，否则新增字段不会生效"
    )
    if url.startswith("postgresql"):
        with engine.connect() as conn:
            autocommit = conn.execution_options(isolation_level="AUTOCOMMIT")
            autocommit.execute(text("SELECT pg_advisory_lock(724512345)"))
            try:
                Base.metadata.create_all(engine)
            finally:
                autocommit.execute(text("SELECT pg_advisory_unlock(724512345)"))
    else:
        Base.metadata.create_all(engine)


@contextmanager
def session_scope(read_only: bool = False):
    """统一数据库会话入口
    - read_only=False（默认）：走主引擎，可读写
    - read_only=True：走只读引擎，适合查询/报表
    """
    factory = ReadSessionLocal if read_only and READ_DATABASE_URL else SessionLocal
    session = factory()
    try:
        yield session
        if not read_only:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ============================================================
# 健康检查
# ============================================================

def check_db_health() -> dict:
    """数据库健康检查（供 /health 接口调用）"""
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        pool = engine.pool
        return {
            "status": "ok",
            "database": "connected",
            "schema_revision": schema_revision(),
            "pool_size": getattr(pool, "size", lambda: 1)(),
            "checked_in": getattr(pool, "checkedin", lambda: 0)(),
            "checked_out": getattr(pool, "checkedout", lambda: 0)(),
            "overflow": getattr(pool, "overflow", lambda: 0)(),
        }
    except Exception as e:
        return {"status": "error", "database": str(e)}
