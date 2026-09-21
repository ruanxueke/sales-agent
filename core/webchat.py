"""网页在线客服：嵌入脚本 + 会话接入（前端挂载点占位，后端可立即复用 /chat）"""
from __future__ import annotations
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime
from pathlib import Path

from config.settings import settings

DB_PATH = Path(settings.DATA_DIR) / "customers.db"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class WebChatManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS webchat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT UNIQUE,
                    visitor_name TEXT DEFAULT '',
                    source_page TEXT DEFAULT '',
                    status TEXT DEFAULT 'open',
                    owner TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS webchat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    role TEXT,
                    content TEXT,
                    created_at TEXT
                );
                """
            )
            self._conn.commit()

    def create_session(self, visitor_name: str = "", source_page: str = "") -> dict:
        import uuid
        key = "wc_" + uuid.uuid4().hex[:12]
        with self._lock:
            self._conn.execute(
                "INSERT INTO webchat_sessions (session_key,visitor_name,source_page,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (key, visitor_name, source_page, "open", _now(), _now()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM webchat_sessions WHERE session_key=?", (key,)).fetchone()
            return dict(row)

    def get_session(self, session_key: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM webchat_sessions WHERE session_key=?", (session_key,)).fetchone()
        return dict(row) if row else None

    def append_message(self, session_key: str, role: str, content: str) -> bool:
        s = self.get_session(session_key)
        if not s:
            return False
        with self._lock:
            self._conn.execute(
                "INSERT INTO webchat_messages (session_id,role,content,created_at) VALUES (?,?,?,?)",
                (s["id"], role, content, _now()),
            )
            self._conn.execute("UPDATE webchat_sessions SET updated_at=? WHERE id=?", (_now(), s["id"]))
            self._conn.commit()
            return True

    def list_sessions(self, status: str = "", limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM webchat_sessions"
        params: tuple = ()
        if status:
            sql += " WHERE status=?"
            params = (status,)
        sql += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in self._conn.execute(sql, params + (limit,)).fetchall()]

    def messages(self, session_key: str, limit: int = 50) -> list[dict]:
        s = self.get_session(session_key)
        if not s:
            return []
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM webchat_messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (s["id"], limit),
        ).fetchall()][::-1]


webchat = WebChatManager()
