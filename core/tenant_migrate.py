"""全表租户隔离迁移：给所有核心业务表加 tenant_id 列（幂等，可重复执行）"""
from __future__ import annotations
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
from pathlib import Path

from config.settings import settings

DB_PATH = Path(settings.DATA_DIR) / "customers.db"

# 需要隔离的业务表（排除纯系统/审计/配置表）
BUSINESS_TABLES = [
    "customers", "leads", "orders", "opportunities", "quotes", "contracts",
    "followup_tasks", "tickets", "visits", "after_sales", "receivables", "invoices",
    "campaigns", "ad_metrics", "nurture_campaigns", "nurture_rules", "nurture_events",
    "appointments", "coupons", "user_coupons", "payment_links", "payment_plans",
    "quality_reports", "conversation_scores", "customer_chat_log", "customer_chat_archive",
    "handover_requests", "sop_executions", "sales_cases", "product_knowledge",
    "objection_responses", "competitor_responses", "followup_scripts", "evidence_library",
    "key_moment_tools", "differentiators", "repurchase_plans", "ticket_events",
    "stage_log", "conversation_summary", "conversation_feedback", "conversation_citations",
]


def migrate():
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        existing = {r[0] for r in rows}
        added = []
        for table in BUSINESS_TABLES:
            if table not in existing:
                continue
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "tenant_id" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id INTEGER DEFAULT 0")
                added.append(table)
        conn.commit()
        result = {"ok": True, "added": added, "tables": len([t for t in BUSINESS_TABLES if t in existing])}
        if not added and not _is_sqlite_backend():
            # 非 SQLite 后端时 DDL 会被 sql_compat 跳过（结构由 alembic 管理）。
            # 这里必须显式说明，否则「什么都没加」会被误读成「已经全都加过了」。
            result["note"] = (
                "当前为 PostgreSQL 后端，ALTER 语句由 sql_compat 跳过；"
                "加列请改用 alembic 迁移（见 migrations/versions/）。"
            )
        return result
    finally:
        conn.close()


def _is_sqlite_backend() -> bool:
    url = settings.DATABASE_URL or ""
    return not url or url.startswith("sqlite")


if __name__ == "__main__":
    import json
    print(json.dumps(migrate(), ensure_ascii=False))
