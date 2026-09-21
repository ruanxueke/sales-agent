"""企业级多租户与权限体系：租户、成员、角色、数据隔离、配额"""
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

ROLES = {"owner", "admin", "manager", "sales", "service", "finance", "viewer"}
PERMISSIONS = {
    "owner": {"*"},
    "admin": {"*"},
    "manager": {"customers.rw", "leads.rw", "orders.rw", "reports.r", "followups.rw", "team.r"},
    "sales": {"customers.rw", "leads.rw", "orders.r", "followups.r", "chat.rw"},
    "service": {"customers.r", "tickets.rw", "orders.r", "chat.r"},
    "finance": {"orders.r", "finance.rw", "reports.r"},
    "viewer": {"customers.r", "leads.r", "reports.r"},
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class TenantManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_key TEXT UNIQUE,
                    name TEXT DEFAULT '',
                    plan TEXT DEFAULT 'trial',
                    status TEXT DEFAULT 'active',
                    seats INTEGER DEFAULT 5,
                    quota_customers INTEGER DEFAULT 500,
                    quota_messages INTEGER DEFAULT 5000,
                    expires_at TEXT DEFAULT '',
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS tenant_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    user_id INTEGER,
                    role TEXT DEFAULT 'sales',
                    status TEXT DEFAULT 'active',
                    created_at TEXT,
                    UNIQUE(tenant_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS tenant_settings (
                    tenant_id INTEGER,
                    key TEXT,
                    value TEXT,
                    PRIMARY KEY(tenant_id, key)
                );
                """
            )
            for col_sql in (
                "ALTER TABLE system_users ADD COLUMN tenant_id INTEGER DEFAULT 0",
                "ALTER TABLE system_users ADD COLUMN display_name TEXT DEFAULT ''",
            ):
                try:
                    self._conn.execute(col_sql)
                except sqlite3.OperationalError as e:
                    err = str(e).lower()
                    if "duplicate column" not in err and "already exists" not in err:
                        logger.warning("补列失败，该列在运行期可能一直缺失: %s -> %s", col_sql, e)
            self._conn.commit()

    def _row(self, sql, params=()):
        cur = self._conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

    def create_tenant(self, name: str, plan: str = "trial", seats: int = 5) -> dict:
        with self._lock:
            key = "t_" + secrets.token_hex(4)
            now = _now()
            expires = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S") if plan == "trial" else ""
            self._conn.execute(
                "INSERT INTO tenants (tenant_key,name,plan,status,seats,expires_at,created_at) VALUES (?,?,?,?,?,?,?)",
                (key, name, plan, "active", seats, expires, now),
            )
            self._conn.commit()
            return self._row("SELECT * FROM tenants WHERE tenant_key=?", (key,))

    def list_tenants(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM tenants ORDER BY id DESC").fetchall()]

    def get_tenant(self, tenant_id: int) -> dict | None:
        return self._row("SELECT * FROM tenants WHERE id=?", (tenant_id,))

    def update_tenant(self, tenant_id: int, **fields) -> dict | None:
        allowed = {"name", "plan", "status", "seats", "quota_customers", "quota_messages", "expires_at"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return self.get_tenant(tenant_id)
        sets["tenant_id"] = tenant_id
        sql = "UPDATE tenants SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?"
        with self._lock:
            self._conn.execute(sql, list(sets.values()))
            self._conn.commit()
        return self.get_tenant(tenant_id)

    def add_member(self, tenant_id: int, user_id: int, role: str = "sales") -> bool:
        if role not in ROLES:
            raise ValueError(f"角色必须是 {sorted(ROLES)}")
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO tenant_members (tenant_id,user_id,role,status,created_at) VALUES (?,?,?,?,?)",
                    (tenant_id, user_id, role, "active", _now()),
                )
                self._conn.execute("UPDATE system_users SET tenant_id=? WHERE id=?", (tenant_id, user_id))
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def update_member_role(self, user_id: int, role: str) -> bool:
        if role not in ROLES:
            raise ValueError(f"角色必须是 {sorted(ROLES)}")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tenant_members SET role=? WHERE user_id=?",
                (role, user_id),
            )
            self._conn.execute("UPDATE system_users SET role=? WHERE id=?", (role, user_id))
            self._conn.commit()
            return cur.rowcount > 0

    def remove_member(self, tenant_id: int, user_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM tenant_members WHERE tenant_id=? AND user_id=?", (tenant_id, user_id))
            self._conn.commit()
            return cur.rowcount > 0

    def list_members(self, tenant_id: int) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT tm.*, su.username, su.name FROM tenant_members tm LEFT JOIN system_users su ON su.id=tm.user_id WHERE tm.tenant_id=?",
            (tenant_id,),
        ).fetchall()]

    def set_setting(self, tenant_id: int, key: str, value: str):
        with self._lock:
            self._conn.execute(
                "INSERT INTO tenant_settings (tenant_id,key,value) VALUES (?,?,?) ON CONFLICT(tenant_id,key) DO UPDATE SET value=excluded.value",
                (tenant_id, key, value),
            )
            self._conn.commit()

    def get_settings(self, tenant_id: int) -> dict:
        return {r["key"]: r["value"] for r in self._conn.execute(
            "SELECT key,value FROM tenant_settings WHERE tenant_id=?", (tenant_id,)
        ).fetchall()}

    def check_quota(self, tenant_id: int, kind: str = "customers") -> tuple[bool, int, int]:
        t = self.get_tenant(tenant_id)
        if not t:
            return False, 0, 0
        field = "quota_customers" if kind == "customers" else "quota_messages"
        quota = t.get(field) or 0
        table = "customers" if kind == "customers" else "customer_chat_log"
        try:
            used = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            used = 0
        return used < quota, used, quota

    def has_permission(self, role: str, perm: str) -> bool:
        perms = PERMISSIONS.get(role, set())
        return "*" in perms or perm in perms


tenant_manager = TenantManager()
