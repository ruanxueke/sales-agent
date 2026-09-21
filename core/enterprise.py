"""企业级销售管理：账号/业绩/佣金/审批规则/SLA与客户分级"""
from __future__ import annotations
import logging
import secrets
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import settings
from core import login_guard
from core.password import hash_password, needs_rehash, verify_password

logger = logging.getLogger(__name__)

DB_PATH = Path(settings.DATA_DIR) / "customers.db"
TOKEN_TTL_HOURS = 24


class EnterpriseManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS system_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    password_hash TEXT,
                    name TEXT DEFAULT '',
                    role TEXT DEFAULT 'sales',
                    status TEXT DEFAULT 'active',
                    tenant_id INTEGER DEFAULT 0,
                    display_name TEXT DEFAULT '',
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT UNIQUE,
                    user_id INTEGER,
                    expires_at TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sales_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member TEXT,
                    period TEXT,
                    target_type TEXT DEFAULT 'amount',
                    amount REAL DEFAULT 0,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS commission_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    rule_type TEXT DEFAULT 'percent',
                    value REAL DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS commission_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    member TEXT,
                    order_amount REAL DEFAULT 0,
                    commission REAL DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS approval_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    biz_type TEXT,
                    name TEXT,
                    condition_key TEXT,
                    operator TEXT DEFAULT '>',
                    threshold REAL DEFAULT 0,
                    approver TEXT DEFAULT '主管',
                    level INTEGER DEFAULT 1,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sla_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    priority TEXT,
                    name TEXT,
                    respond_hours REAL DEFAULT 2,
                    resolve_hours REAL DEFAULT 24,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS customer_tiers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tier TEXT,
                    name TEXT,
                    min_amount REAL DEFAULT 0,
                    priority_boost INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT
                );
                """
            )
            # 老库补列：tenant_id / display_name 原本由 core/tenant.py 在导入时用 ALTER
            # 现补，于是"只导入 enterprise 而不导入 tenant"的路径下 system_users 根本没
            # 这两列，登录成功那一刻就 KeyError('tenant_id')。谁读这一列，谁负责保证它
            # 存在。新库已由上面的 CREATE TABLE 带上，这里只对历史库生效。
            # PostgreSQL 上 DDL 会被 sql_compat 跳过，结构统一归迁移链（0008）管。
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

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---------- 账号 ----------
    def create_user(
        self,
        username: str,
        password: str,
        name: str = "",
        role: str = "sales",
        tenant_id: int = 0,
    ) -> dict:
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO system_users (username, password_hash, name, role, status, tenant_id, created_at) VALUES (?, ?, ?, ?, 'active', ?, ?)",
                    (username, hash_password(password), name, role, int(tenant_id or 0), self._now()),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError("用户名已存在") from e
            return self.get_user(cur.lastrowid)

    def get_user(self, user_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM system_users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM system_users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def list_users(self, tenant_id: int | None = None) -> list[dict]:
        with self._lock:
            if tenant_id is None:
                rows = self._conn.execute(
                    "SELECT id, username, name, role, status, tenant_id, created_at FROM system_users ORDER BY id"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, username, name, role, status, tenant_id, created_at FROM system_users WHERE tenant_id=? ORDER BY id",
                    (int(tenant_id),),
                ).fetchall()
        return [dict(r) for r in rows]

    def set_user_status(self, user_id: int, status: str, tenant_id: int | None = None) -> bool:
        with self._lock:
            if tenant_id is None:
                cur = self._conn.execute(
                    "UPDATE system_users SET status = ? WHERE id = ?", (status, user_id)
                )
            else:
                cur = self._conn.execute(
                    "UPDATE system_users SET status = ? WHERE id = ? AND tenant_id = ?",
                    (status, user_id, int(tenant_id)),
                )
            self._conn.commit()
            return cur.rowcount > 0

    def login(self, username: str, password: str, ip: str = "") -> dict | None:
        """账号口令登录。

        锁定状态放 Redis（多 worker 共享，重启不清零），详见 core.login_guard。
        口令校验走 PBKDF2，同时兼容历史 `sha256(用户名+口令)` 旧哈希，并在登录成功后
        就地升级为新格式。
        """
        username = (username or "").strip()
        if not username or not password:
            return None

        locked = login_guard.locked_seconds(username)
        if locked > 0:
            logger.warning("账号 %s 处于登录锁定期，剩余 %s 秒，拒绝登录", username, locked)
            return None
        if ip:
            ip_locked = login_guard.locked_seconds("ip:" + ip)
            if ip_locked > 0:
                logger.warning("来源 IP %s 触发登录限流，剩余 %s 秒", ip, ip_locked)
                return None

        user = self.get_user_by_username(username)

        def _fail(reason: str) -> None:
            count, locked_for = login_guard.record_failure(username)
            if ip:
                login_guard.record_failure(
                    "ip:" + ip,
                    limit=login_guard.IP_MAX_FAILURES,
                    window=login_guard.FAIL_WINDOW,
                    lock_seconds=login_guard.LOCK_SECONDS,
                )
            logger.warning(
                "登录失败 username=%s ip=%s 原因=%s 窗口内累计=%s%s",
                username, ip or "-", reason, count,
                "，已锁定 %s 秒" % locked_for if locked_for else "",
            )

        if not user or user["status"] != "active":
            # 账号不存在/被停用也照常计数，避免用响应差异枚举用户名。
            _fail("账号不存在或已停用")
            return None

        if not verify_password(password, user["password_hash"], legacy_salt=username):
            _fail("口令不匹配")
            return None

        login_guard.clear(username)
        if ip:
            login_guard.clear("ip:" + ip)
        self._upgrade_password_hash(user, password)

        token = secrets.token_urlsafe(32)
        expires = (datetime.now() + timedelta(hours=TOKEN_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_tokens (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token, user["id"], expires, self._now()),
            )
            self._conn.commit()
        return {"token": token, "user": {k: user[k] for k in ("id", "username", "name", "role", "tenant_id")}}

    def _upgrade_password_hash(self, user: dict, password: str) -> None:
        """登录成功后把旧格式/低迭代的哈希原地升级为当前 KDF 参数。

        放在登录成功之后做，失败不影响本次登录结果——升级只是"顺手把债还掉"。
        """
        try:
            if not needs_rehash(user.get("password_hash") or ""):
                return
            with self._lock:
                self._conn.execute(
                    "UPDATE system_users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), user["id"]),
                )
                self._conn.commit()
            logger.info("账号 %s 的口令哈希已升级为 %s", user.get("username"), "pbkdf2_sha256")
        except Exception as e:
            logger.warning("口令哈希升级失败（不影响本次登录）: %s", e)

    def get_user_by_token(self, token: str) -> dict | None:
        if not token:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT u.* FROM auth_tokens t JOIN system_users u ON u.id = t.user_id "
                "WHERE t.token = ? AND t.expires_at > ? AND u.status = 'active'",
                (token, self._now()),
            ).fetchone()
        return dict(row) if row else None

    # ---------- 业绩 / 佣金 ----------
    def performance(self, period: str = "") -> list[dict]:
        sql = (
            "SELECT COALESCE(l.owner, '未分配') AS member, "
            "COUNT(o.id) AS orders, ROUND(SUM(o.amount), 2) AS amount "
            "FROM orders o LEFT JOIN leads l ON l.id = o.lead_id "
            "WHERE o.status = 'paid' GROUP BY member ORDER BY amount DESC"
        )
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def leaderboard(self, period: str = "") -> list[dict]:
        return self.performance(period)

    def create_target(self, member: str, period: str, target_type: str = "amount", amount: float = 0) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sales_targets (member, period, target_type, amount, created_at) VALUES (?, ?, ?, ?, ?)",
                (member, period, target_type, amount, self._now()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM sales_targets WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def list_targets(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sales_targets ORDER BY id DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]

    def create_commission_rule(self, name: str, rule_type: str = "percent", value: float = 0) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO commission_rules (name, rule_type, value, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
                (name, rule_type, value, self._now()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM commission_rules WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def list_commission_rules(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM commission_rules ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def compute_commissions(self) -> dict:
        with self._lock:
            rules = self._conn.execute(
                "SELECT * FROM commission_rules WHERE enabled = 1 ORDER BY id"
            ).fetchall()
            paid = self._conn.execute(
                "SELECT o.id AS order_id, COALESCE(l.owner, '未分配') AS member, o.amount "
                "FROM orders o LEFT JOIN leads l ON l.id = o.lead_id "
                "WHERE o.status = 'paid' AND o.id NOT IN (SELECT order_id FROM commission_records)"
            ).fetchall()
            created = 0
            for order in paid:
                rule = rules[0] if rules else None
                if not rule:
                    break
                commission = round(order["amount"] * rule["value"] / 100, 2) if rule["rule_type"] == "percent" else round(rule["value"], 2)
                self._conn.execute(
                    "INSERT INTO commission_records (order_id, member, order_amount, commission, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                    (order["order_id"], order["member"], order["amount"], commission, self._now()),
                )
                created += 1
            self._conn.commit()
        return {"created": created}

    def list_commissions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM commission_records ORDER BY id DESC LIMIT 300").fetchall()
        return [dict(r) for r in rows]

    # ---------- 审批规则 ----------
    def create_approval_rule(self, biz_type: str, name: str, condition_key: str,
                             operator: str = ">", threshold: float = 0,
                             approver: str = "主管", level: int = 1) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO approval_rules (biz_type, name, condition_key, operator, threshold, approver, level, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (biz_type, name, condition_key, operator, threshold, approver, level, self._now()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM approval_rules WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def list_approval_rules(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM approval_rules ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def delete_approval_rule(self, rule_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM approval_rules WHERE id = ?", (rule_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def check_approval_rules(self, biz_type: str, data: dict) -> list[dict]:
        matched = []
        for rule in self.list_approval_rules():
            if not rule["enabled"] or rule["biz_type"] != biz_type:
                continue
            value = float(data.get(rule["condition_key"]) or 0)
            threshold = float(rule["threshold"] or 0)
            hit = value > threshold if rule["operator"] == ">" else value >= threshold
            if hit:
                matched.append(rule)
        return matched

    def create_approval(self, biz_type: str, biz_id: int, rule: dict) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO approval_flows (biz_type, biz_id, requester, approver, status, comment, created_at, updated_at) "
                "VALUES (?, ?, 'system', ?, 'requested', ?, ?, ?)",
                (biz_type, biz_id, rule.get("approver") or "主管",
                 f"规则:{rule.get('name')} 级别:{rule.get('level')}",
                 self._now(), self._now()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM approval_flows WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    # ---------- SLA / 客户分级 ----------
    def create_sla_policy(self, priority: str, name: str, respond_hours: float = 2,
                          resolve_hours: float = 24) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sla_policies (priority, name, respond_hours, resolve_hours, enabled, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (priority, name, respond_hours, resolve_hours, self._now()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM sla_policies WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def list_sla_policies(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sla_policies ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def sla_resolve_hours(self, priority: str) -> float:
        row = None
        with self._lock:
            row = self._conn.execute(
                "SELECT resolve_hours FROM sla_policies WHERE priority = ? AND enabled = 1 ORDER BY id LIMIT 1",
                (priority,),
            ).fetchone()
        return float(row["resolve_hours"]) if row else 24.0

    def create_customer_tier(self, tier: str, name: str, min_amount: float = 0,
                             priority_boost: int = 0) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO customer_tiers (tier, name, min_amount, priority_boost, enabled, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (tier, name, min_amount, priority_boost, self._now()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM customer_tiers WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def list_customer_tiers(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM customer_tiers ORDER BY min_amount DESC").fetchall()
        return [dict(r) for r in rows]


enterprise = EnterpriseManager()
