"""销售客户档案（CRM）：SQLite 存储客户信息、销售阶段与阶段变更记录"""
from __future__ import annotations
import json
import logging
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import settings
from core.sales_constants import PROFILE_FIELDS, STAGE_RANK, STAGES

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class CustomerCRM:
    """客户档案数据库，线程安全"""

    def __init__(self, db_path: Optional[Path] = None):
        self._path = str(db_path or (settings.DATA_DIR / "customers.db"))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        logger.info("客户档案库已初始化: %s", self._path)

    def _init_db(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    nickname TEXT DEFAULT '',
                    source TEXT DEFAULT 'wechat',
                    display_id TEXT DEFAULT '',
                    name TEXT DEFAULT '',
                    phone TEXT DEFAULT '',
                    wechat_id TEXT DEFAULT '',
                    identity TEXT DEFAULT '',
                    level TEXT DEFAULT '',
                    goal TEXT DEFAULT '',
                    budget TEXT DEFAULT '',
                    interest TEXT DEFAULT '',
                    stage TEXT DEFAULT 'new',
                    intent_level TEXT DEFAULT '',
                    intent_score INTEGER DEFAULT 0,
                    notes TEXT DEFAULT '',
                    next_follow_up TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
                CREATE TABLE IF NOT EXISTS stage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    from_stage TEXT DEFAULT '',
                    to_stage TEXT NOT NULL,
                    trigger TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
                CREATE TABLE IF NOT EXISTS customer_chat_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
                CREATE TABLE IF NOT EXISTS customer_chat_archive (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT '',
                    archived_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    target TEXT DEFAULT '',
                    content TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
                """
            )
            # 多租户预留：旧库补 tenant_id 列
            for col_sql in (
                "ALTER TABLE customers ADD COLUMN tenant_id INTEGER DEFAULT 0",
                "ALTER TABLE leads ADD COLUMN tenant_id INTEGER DEFAULT 0",
                "ALTER TABLE orders ADD COLUMN tenant_id INTEGER DEFAULT 0",
            ):
                try:
                    self._conn.execute(col_sql)
                except Exception as e:
                    err = str(e).lower()
                    if "duplicate column" not in err and "already exists" not in err:
                        logger.warning("补列失败，该列在运行期可能一直缺失: %s -> %s", col_sql, e)
            self._conn.commit()
            self._conn.commit()
            cols = [row[1] for row in self._conn.execute("PRAGMA table_info(customers)").fetchall()]
            if "intent_level" not in cols:
                self._conn.execute("ALTER TABLE customers ADD COLUMN intent_level TEXT DEFAULT ''")
                self._conn.commit()
            if "sales_status" not in cols:
                self._conn.execute("ALTER TABLE customers ADD COLUMN sales_status TEXT DEFAULT 'new_lead'")
                self._conn.commit()
            if "display_id" not in cols:
                self._conn.execute("ALTER TABLE customers ADD COLUMN display_id TEXT DEFAULT ''")
                self._conn.commit()

    def get_or_create(self, session_id: str, nickname: str = "", source: str = "wechat") -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM customers WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row:
                if nickname and row["nickname"] != nickname:
                    old_name = str(row["nickname"] or "").strip()
                    display_id = (
                        self._make_display_id(nickname, exclude_id=row["id"])
                        if self._display_id_follows_name(row["display_id"], old_name)
                        else row["display_id"]
                    )
                    self._conn.execute(
                        "UPDATE customers SET nickname = ?, display_id = ?, updated_at = ? WHERE id = ?",
                        (nickname, display_id, _now(), row["id"]),
                    )
                    self._conn.commit()
                if not row["display_id"]:
                    display_id = (
                        self._make_display_id(nickname, exclude_id=row["id"])
                        or f"客户{row['id']}"
                    )
                    self._conn.execute(
                        "UPDATE customers SET display_id = ?, updated_at = ? WHERE id = ?",
                        (display_id, _now(), row["id"]),
                    )
                    self._conn.commit()
                return dict(self._conn.execute(
                    "SELECT * FROM customers WHERE id = ?", (row["id"],)
                ).fetchone())
            cur = self._conn.execute(
                "INSERT INTO customers (session_id, nickname, source) VALUES (?, ?, ?)",
                (session_id, nickname, source),
            )
            self._conn.commit()
            display_id = self._make_display_id(nickname) or f"客户{cur.lastrowid}"
            self._conn.execute(
                "UPDATE customers SET display_id = ? WHERE id = ?",
                (display_id, cur.lastrowid),
            )
            self._conn.commit()
            return dict(self._conn.execute(
                "SELECT * FROM customers WHERE id = ?", (cur.lastrowid,)
            ).fetchone())

    @staticmethod
    def _display_id_follows_name(display_id: str, old_name: str) -> bool:
        display_id = str(display_id or "").strip()
        old_name = str(old_name or "").strip()
        if not display_id:
            return True
        if old_name and display_id == old_name:
            return True
        if old_name and display_id.startswith(old_name):
            return display_id[len(old_name):].isdigit()
        return False

    def _make_display_id(self, nickname: str, exclude_id: int | None = None) -> str:
        """根据微信昵称生成唯一显示ID，重复时追加 2、3..."""
        nickname = (nickname or "").strip()
        if not nickname:
            return ""
        if exclude_id is None:
            used = {r[0] for r in self._conn.execute(
                "SELECT display_id FROM customers WHERE display_id != ''"
            ).fetchall()}
        else:
            used = {r[0] for r in self._conn.execute(
                "SELECT display_id FROM customers WHERE display_id != '' AND id != ?",
                (exclude_id,),
            ).fetchall()}
        if nickname not in used:
            return nickname
        index = 2
        while f"{nickname}{index}" in used:
            index += 1
        return f"{nickname}{index}"


    def get(self, customer_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_by_session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM customers WHERE session_id = ?", (session_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_customers(self, tenant_id: int | None = None) -> list[dict]:
        with self._lock:
            if tenant_id is not None:
                rows = self._conn.execute(
                    "SELECT * FROM customers WHERE tenant_id=? ORDER BY updated_at DESC", (tenant_id,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM customers ORDER BY updated_at DESC").fetchall()
            return [dict(r) for r in rows]

    def update_profile(self, customer_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in PROFILE_FIELDS}
        if not allowed:
            return
        with self._lock:
            if "nickname" in allowed and not allowed.get("display_id"):
                row = self._conn.execute(
                    "SELECT display_id, nickname FROM customers WHERE id = ?",
                    (customer_id,),
                ).fetchone()
                if row and (
                    not row["display_id"]
                    or self._display_id_follows_name(
                        row["display_id"],
                        row["nickname"],
                    )
                ):
                    allowed["display_id"] = self._make_display_id(
                        allowed["nickname"],
                        exclude_id=customer_id,
                    )
            sets = ", ".join(f"{k} = ?" for k in allowed)
            self._conn.execute(
                f"UPDATE customers SET {sets}, updated_at = ? WHERE id = ?",
                (*allowed.values(), _now(), customer_id),
            )
            self._conn.commit()

    def advance_stage(self, customer_id: int, new_stage: str, trigger: str = "") -> str:
        if new_stage not in STAGE_RANK:
            raise ValueError(f"未知阶段: {new_stage}")
        with self._lock:
            row = self._conn.execute(
                "SELECT stage FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            if not row:
                return "new"
            old_stage = row["stage"]
            if old_stage == new_stage:
                return old_stage
            self._conn.execute(
                "UPDATE customers SET stage = ?, updated_at = ? WHERE id = ?",
                (new_stage, _now(), customer_id),
            )
            self._conn.execute(
                "INSERT INTO stage_log (customer_id, from_stage, to_stage, trigger) VALUES (?, ?, ?, ?)",
                (customer_id, old_stage, new_stage, trigger[:200]),
            )
            self._conn.commit()
            logger.info("客户 %s 阶段变化: %s -> %s (%s)", customer_id, old_stage, new_stage, trigger[:50])
            self._notify_sop(customer_id, new_stage)
            return new_stage

    @staticmethod
    def _notify_sop(customer_id: int, stage: str) -> None:
        try:
            from core.sop import sop_manager
            sop_manager.on_stage_change(customer_id, stage)
        except Exception as e:
            logger.error(f"SOP阶段联动失败: {e}")

    def stage_log(self, customer_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM stage_log WHERE customer_id = ? ORDER BY id",
                (customer_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def append_chat(self, customer_id: int, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO customer_chat_log (customer_id, role, content) VALUES (?, ?, ?)",
                (customer_id, role, content),
            )
            self._conn.commit()
            self._trim_chat_log(customer_id)

    def _trim_chat_log(self, customer_id: int) -> None:
        """活跃聊天记录超过上限时归档最旧的，归档也设上限"""
        max_entries = settings.CHAT_LOG_MAX_ENTRIES_PER_CUSTOMER
        rows = self._conn.execute(
            "SELECT id, role, content, created_at FROM customer_chat_log "
            "WHERE customer_id = ? ORDER BY id ASC",
            (customer_id,),
        ).fetchall()
        overflow = len(rows) - max_entries
        if overflow <= 0:
            return
        for row in rows[:overflow]:
            self._conn.execute(
                "INSERT INTO customer_chat_archive (customer_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (customer_id, row["role"], row["content"], row["created_at"]),
            )
            self._conn.execute("DELETE FROM customer_chat_log WHERE id = ?", (row["id"],))
        self._conn.commit()

        archive_rows = self._conn.execute(
            "SELECT id FROM customer_chat_archive WHERE customer_id = ? ORDER BY id ASC",
            (customer_id,),
        ).fetchall()
        archive_cap = settings.CHAT_LOG_ARCHIVE_MAX_ENTRIES_PER_CUSTOMER
        if len(archive_rows) > archive_cap:
            for row in archive_rows[:len(archive_rows) - archive_cap]:
                self._conn.execute("DELETE FROM customer_chat_archive WHERE id = ?", (row["id"],))
            self._conn.commit()

    def get_chat_log(self, customer_id: int, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM customer_chat_log WHERE customer_id = ? ORDER BY id DESC LIMIT ?",
                (customer_id, limit),
            ).fetchall()
            return list(reversed([dict(r) for r in rows]))

    def create_notification(self, customer_id: int, target: str, content: str, status: str = "pending") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO notifications (customer_id, target, content, status) VALUES (?, ?, ?, ?)",
                (customer_id, target, content, status),
            )
            self._conn.commit()
            new_id = cur.lastrowid
        try:
            from core.realtime import hub
            hub.publish_sync({"type": "notification", "id": new_id, "content": content, "customer_id": customer_id})
        except Exception as e:
            logger.debug("CustomerCRM.create_notification 异常已忽略: %s", e)
        return new_id

    def list_notifications(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def count_today_messages(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM customer_chat_log "
                "WHERE created_at >= date('now', 'localtime')"
            ).fetchone()
            return row["c"] if row else 0

    def update_notification_status(self, notification_id: int, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE notifications SET status = ? WHERE id = ?",
                (status, notification_id),
            )
            self._conn.commit()


class RedisCustomerCRM:
    """客户档案 Redis 后端：适合多实例、高并发场景"""

    def __init__(self, redis):
        self._redis = redis
        self._lock = threading.RLock()

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _customer_key(session_id: str) -> str:
        return f"crm:customer:{session_id}"

    @staticmethod
    def _id_key(customer_id: int) -> str:
        return f"crm:customer_id:{customer_id}"

    def _to_dict(self, raw: dict) -> dict:
        result = {}
        for k, v in raw.items():
            key = k.decode() if isinstance(k, bytes) else k
            value = v.decode() if isinstance(v, bytes) else v
            if key == "intent_score":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = 0
            result[key] = value
        return result

    def get_or_create(self, session_id: str, nickname: str = "", source: str = "wechat") -> dict:
        key = self._customer_key(session_id)
        with self._lock:
            if self._redis.exists(key):
                if nickname and self._redis.hget(key, "nickname") != nickname:
                    old_name = self._redis.hget(key, "nickname") or ""
                    display_id = self._redis.hget(key, "display_id") or ""
                    mapping = {"nickname": nickname, "updated_at": self._now()}
                    if self._display_id_follows_name(display_id, old_name):
                        mapping["display_id"] = nickname
                    self._redis.hset(key, mapping=mapping)
                return self._to_dict(self._redis.hgetall(key))
            customer_id = self._redis.incr("crm:next_id")
            now = self._now()
            self._redis.hset(key, mapping={
                "id": customer_id,
                "session_id": session_id,
                "nickname": nickname or "",
                "display_id": nickname or "",
                "source": source,
                "name": "",
                "phone": "",
                "wechat_id": "",
                "identity": "",
                "level": "",
                "goal": "",
                "budget": "",
                "interest": "",
                "stage": "new",
                "intent_level": "",
                "intent_score": 0,
                "notes": "",
                "next_follow_up": "",
                "created_at": now,
                "updated_at": now,
            })
            self._redis.set(self._id_key(customer_id), session_id)
            return self._to_dict(self._redis.hgetall(key))

    def get(self, customer_id: int) -> Optional[dict]:
        with self._lock:
            session_id = self._redis.get(self._id_key(customer_id))
            if not session_id:
                return None
            raw = self._redis.hgetall(self._customer_key(session_id))
            return self._to_dict(raw) if raw else None

    def get_by_session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            raw = self._redis.hgetall(self._customer_key(session_id))
            return self._to_dict(raw) if raw else None

    def list_customers(self) -> list[dict]:
        with self._lock:
            customers = []
            for key in self._redis.scan_iter(match="crm:customer:*"):
                if b"customer_id:" in (key if isinstance(key, bytes) else key.encode()):
                    continue
                customers.append(self._to_dict(self._redis.hgetall(key)))
            customers.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
            return customers

    def update_profile(self, customer_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in PROFILE_FIELDS}
        if not allowed:
            return
        with self._lock:
            session_id = self._redis.get(self._id_key(customer_id))
            if not session_id:
                return
            allowed["updated_at"] = self._now()
            if allowed.get("nickname"):
                current_name = self._redis.hget(self._customer_key(session_id), "nickname") or ""
                display_id = self._redis.hget(self._customer_key(session_id), "display_id") or ""
                if self._display_id_follows_name(display_id, current_name):
                    allowed["display_id"] = allowed["nickname"]
            self._redis.hset(self._customer_key(session_id), mapping=allowed)

    @staticmethod
    def _display_id_follows_name(display_id: str, old_name: str) -> bool:
        display_id = str(display_id or "").strip()
        old_name = str(old_name or "").strip()
        if not display_id:
            return True
        if old_name and display_id == old_name:
            return True
        if old_name and display_id.startswith(old_name):
            return display_id[len(old_name):].isdigit()
        return False

    def advance_stage(self, customer_id: int, new_stage: str, trigger: str = "") -> str:
        if new_stage not in STAGE_RANK:
            raise ValueError(f"未知阶段: {new_stage}")
        with self._lock:
            session_id = self._redis.get(self._id_key(customer_id))
            if not session_id:
                return "new"
            key = self._customer_key(session_id)
            old_stage = self._redis.hget(key, "stage") or "new"
            if old_stage == new_stage:
                return old_stage
            self._redis.hset(key, mapping={"stage": new_stage, "updated_at": self._now()})
            self._redis.rpush(
                f"crm:stage:{customer_id}",
                json.dumps({
                    "from_stage": old_stage,
                    "to_stage": new_stage,
                    "trigger": trigger[:200],
                    "created_at": self._now(),
                }, ensure_ascii=False),
            )
            logger.info("客户 %s 阶段变化: %s -> %s (%s)", customer_id, old_stage, new_stage, trigger[:50])
            self._notify_sop(customer_id, new_stage)
            return new_stage

    @staticmethod
    def _notify_sop(customer_id: int, stage: str) -> None:
        try:
            from core.sop import sop_manager
            sop_manager.on_stage_change(customer_id, stage)
        except Exception as e:
            logger.error(f"SOP阶段联动失败: {e}")

    def stage_log(self, customer_id: int) -> list[dict]:
        with self._lock:
            rows = self._redis.lrange(f"crm:stage:{customer_id}", 0, -1)
            return [json.loads(r) for r in rows]

    def append_chat(self, customer_id: int, role: str, content: str) -> None:
        with self._lock:
            key = f"crm:chat:{customer_id}"
            archive_key = f"crm:chat_archive:{customer_id}"
            self._redis.rpush(
                key,
                json.dumps({"role": role, "content": content, "created_at": self._now()}, ensure_ascii=False),
            )
            max_entries = settings.CHAT_LOG_MAX_ENTRIES_PER_CUSTOMER
            length = self._redis.llen(key)
            if length > max_entries:
                overflow = length - max_entries
                for _ in range(overflow):
                    item = self._redis.lpop(key)
                    if item:
                        self._redis.rpush(archive_key, item)
                archive_cap = settings.CHAT_LOG_ARCHIVE_MAX_ENTRIES_PER_CUSTOMER
                archive_len = self._redis.llen(archive_key)
                if archive_len > archive_cap:
                    self._redis.ltrim(archive_key, archive_len - archive_cap, -1)

    def get_chat_log(self, customer_id: int, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._redis.lrange(f"crm:chat:{customer_id}", -limit, -1)
            return [json.loads(r) for r in rows]

    def create_notification(self, customer_id: int, target: str, content: str, status: str = "pending") -> int:
        with self._lock:
            notification_id = self._redis.incr("crm:notif_id")
            self._redis.rpush(
                "crm:notifications",
                json.dumps({
                    "id": notification_id,
                    "customer_id": customer_id,
                    "target": target,
                    "content": content,
                    "status": status,
                    "created_at": self._now(),
                }, ensure_ascii=False),
            )
            return notification_id

    def list_notifications(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._redis.lrange("crm:notifications", -limit, -1)
            items = [json.loads(r) for r in rows]
            items.reverse()
            return items

    def count_today_messages(self) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        total = 0
        for c in self.list_customers():
            for item in self.get_chat_log(c["id"], limit=100):
                if item.get("created_at", "").startswith(today):
                    total += 1
        return total

    def update_notification_status(self, notification_id: int, status: str) -> None:
        with self._lock:
            rows = self._redis.lrange("crm:notifications", 0, -1)
            for i, raw in enumerate(rows):
                item = json.loads(raw)
                if item["id"] == notification_id:
                    item["status"] = status
                    self._redis.lset(
                        "crm:notifications",
                        i,
                        json.dumps(item, ensure_ascii=False),
                    )
                    break


def _create_crm():
    if getattr(settings, "DATABASE_URL", None):
        from core.db import init_db
        from core.sales_crm_sa import SQLAlchemyCRM
        init_db()
        logger.info("客户档案库使用 SQLAlchemy 后端: %s", settings.DATABASE_URL.split("://")[0])
        return SQLAlchemyCRM()
    if getattr(settings, "REDIS_URL", None):
        from redis import Redis
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        logger.info("客户档案库使用 Redis 后端")
        return RedisCustomerCRM(client)
    return CustomerCRM()


crm = _create_crm()
