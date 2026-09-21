"""计费与自助注册：套餐、订阅、用量计量、订单式开通（外部支付网关占位）"""
from __future__ import annotations
import secrets
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import settings
import logging
logger = logging.getLogger(__name__)


DB_PATH = Path(settings.DATA_DIR) / "customers.db"

PLANS = {
    "trial": {"name": "试用版", "price_month": 0, "seats": 5, "customers": 500, "messages": 5000},
    "pro": {"name": "专业版", "price_month": 199, "seats": 20, "customers": 5000, "messages": 50000},
    "enterprise": {"name": "企业版", "price_month": 999, "seats": 200, "customers": 50000, "messages": 500000},
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BillingManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    plan TEXT DEFAULT 'trial',
                    status TEXT DEFAULT 'active',
                    started_at TEXT,
                    expires_at TEXT,
                    auto_renew INTEGER DEFAULT 0,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    metric TEXT DEFAULT 'message',
                    amount INTEGER DEFAULT 1,
                    billed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    plan TEXT,
                    amount REAL DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    provider TEXT DEFAULT '',
                    provider_trade_no TEXT DEFAULT '',
                    paid_at TEXT DEFAULT '',
                    created_at TEXT
                );
                """
            )
            self._conn.commit()

    def get_subscription(self, tenant_id: int) -> dict | None:
        cur = self._conn.execute("SELECT * FROM subscriptions WHERE tenant_id=? ORDER BY id DESC LIMIT 1", (tenant_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def subscribe(self, tenant_id: int, plan: str, days: int = 30) -> dict:
        if plan not in PLANS:
            raise ValueError(f"未知套餐: {plan}")
        now = datetime.now()
        with self._lock:
            existing = self.get_subscription(tenant_id)
            start = now
            if existing and existing.get("status") == "active":
                try:
                    exp = datetime.strptime(existing["expires_at"], "%Y-%m-%d %H:%M:%S")
                    if exp > now:
                        start = exp
                except Exception as e:
                    logger.warning("解析已有订阅到期时间失败，续费起点将按当前时间计算: %s", e)
            expires = start + timedelta(days=days)
            self._conn.execute(
                "INSERT INTO subscriptions (tenant_id,plan,status,started_at,expires_at,auto_renew,created_at) VALUES (?,?,?,?,?,?,?)",
                (tenant_id, plan, "active", start.strftime("%Y-%m-%d %H:%M:%S"), expires.strftime("%Y-%m-%d %H:%M:%S"), 0, _now()),
            )
            self._conn.execute("UPDATE tenants SET plan=?, seats=? WHERE id=?", (plan, PLANS[plan]["seats"], tenant_id))
            self._conn.commit()
            return self.get_subscription(tenant_id)

    def cancel(self, tenant_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("UPDATE subscriptions SET status='cancelled' WHERE tenant_id=?", (tenant_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def record_usage(self, tenant_id: int, metric: str = "message", amount: int = 1):
        with self._lock:
            self._conn.execute(
                "INSERT INTO usage_ledger (tenant_id,metric,amount,billed_at) VALUES (?,?,?,?)",
                (tenant_id, metric, amount, _now()),
            )
            self._conn.commit()

    def usage(self, tenant_id: int, metric: str = "message", days: int = 30) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM usage_ledger WHERE tenant_id=? AND metric=? AND billed_at>=?",
            (tenant_id, metric, cutoff),
        ).fetchone()
        return int(row["total"])

    def create_invoice(self, tenant_id: int, plan: str) -> dict:
        amount = PLANS.get(plan, {}).get("price_month", 0)
        with self._lock:
            self._conn.execute(
                "INSERT INTO invoices (tenant_id,plan,amount,status,created_at) VALUES (?,?,?,?,?)",
                (tenant_id, plan, amount, "pending", _now()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM invoices WHERE tenant_id=? ORDER BY id DESC LIMIT 1", (tenant_id,)).fetchone()
            return dict(row)

    def mark_paid(self, invoice_id: int, provider: str = "", trade_no: str = "") -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE invoices SET status='paid', provider=?, provider_trade_no=?, paid_at=? WHERE id=? AND status='pending'",
                (provider, trade_no, _now(), invoice_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_invoices(self, tenant_id: int = 0, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM invoices"
        params: tuple = ()
        if tenant_id:
            sql += " WHERE tenant_id=?"
            params = (tenant_id,)
        sql += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in self._conn.execute(sql, params + (limit,)).fetchall()]

    def health(self) -> dict:
        return {
            "configured": False,
            "payment_provider": settings.PAYMENT_PROVIDER or "unconfigured",
            "note": "外部支付网关未配置，保留接口与占位；可在 .env 配置 PAYMENT_PROVIDER/PAYMENT_* 后启用",
            "plans": PLANS,
        }


billing = BillingManager()
