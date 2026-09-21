"""操作审计：敏感操作写入 JSONL 审计日志，同时落库供查询"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta

from config.settings import settings
from core.db import init_db, session_scope
from core.models import AuditLog

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _ensure_columns():
    try:
        from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
        db = settings.DATA_DIR / "customers.db"
        if not db.exists():
            return
        conn = sqlite3.connect(str(db))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_logs)")}
        if "level" not in cols:
            conn.execute("ALTER TABLE audit_logs ADD COLUMN level TEXT DEFAULT 'info'")
        if "category" not in cols:
            conn.execute("ALTER TABLE audit_logs ADD COLUMN category TEXT DEFAULT 'system'")
        if "tenant_id" not in cols:
            conn.execute("ALTER TABLE audit_logs ADD COLUMN tenant_id INTEGER DEFAULT 0")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"审计字段迁移失败: {e}")


def audit(
    actor: str,
    action: str,
    resource: str = "",
    detail: str = "",
    ip: str = "",
    level: str = "info",
    category: str = "system",
    tenant_id: int = 0,
) -> None:
    """记录一条审计日志；任何异常都不影响主流程"""
    _ensure_columns()
    try:
        log_dir = settings.DATA_DIR / "audit"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        from core.privacy import mask_pii
        record = {
            "time": _now(),
            "actor": actor or "system",
            "action": action,
            "resource": resource or "",
            "detail": mask_pii(detail or ""),
            "ip": ip or "",
            "level": level,
            "category": category,
            "tenant_id": int(tenant_id or 0),
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        init_db()
        with session_scope() as session:
            session.add(AuditLog(
                actor=record["actor"],
                action=record["action"],
                resource=record["resource"],
                detail=record["detail"],
                ip=record["ip"],
                level=record["level"],
                category=record["category"],
                tenant_id=record["tenant_id"],
                created_at=record["time"],
            ))
    except Exception as e:
        logger.error(f"审计日志写入失败: {e}")


def purge_audit(retain_days: int = None) -> dict:
    """按留存周期清理过期审计日志（数据库 + JSONL 文件）"""
    retain_days = retain_days or getattr(settings, "AUDIT_RETENTION_DAYS", 180)
    cutoff = (datetime.now() - timedelta(days=retain_days)).strftime("%Y-%m-%d %H:%M:%S")
    removed_db = 0
    try:
        _ensure_columns()
        init_db()
        with session_scope() as session:
            from sqlalchemy import delete
            res = session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
            session.commit()
            removed_db = res.rowcount or 0
    except Exception as e:
        logger.error(f"审计日志清理失败: {e}")
    removed_files = 0
    try:
        log_dir = settings.DATA_DIR / "audit"
        if log_dir.exists():
            cutoff_file = (datetime.now() - timedelta(days=retain_days)).strftime("%Y-%m-%d")
            for f in log_dir.glob("*.jsonl"):
                if f.stem < cutoff_file:
                    f.unlink(missing_ok=True)
                    removed_files += 1
    except Exception as e:
        logger.error(f"审计文件清理失败: {e}")
    return {"removed_db": removed_db, "removed_files": removed_files}

def list_audit(
    limit: int = 200,
    level: str = "",
    category: str = "",
    tenant_id: int | None = None,
) -> list[dict]:
    try:
        _ensure_columns()
        init_db()
        with session_scope() as session:
            from sqlalchemy import select
            query = select(AuditLog)
            if tenant_id is not None:
                query = query.where(AuditLog.tenant_id == int(tenant_id))
            if level:
                query = query.where(AuditLog.level == level)
            if category:
                query = query.where(AuditLog.category == category)
            rows = session.execute(
                query.order_by(AuditLog.id.desc()).limit(limit)
            ).scalars().all()
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rows
            ]
    except Exception as e:
        logger.error(f"审计日志查询失败: {e}")
        return []
