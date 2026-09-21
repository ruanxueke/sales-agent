"""会话引用溯源与工具调用记录"""
from __future__ import annotations
import json
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime
from pathlib import Path

from config.settings import settings

logger = __import__("logging").getLogger(__name__)

DB_PATH = Path(settings.DATA_DIR) / "customers.db"


class CitationManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_citations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT DEFAULT '',
                    message TEXT DEFAULT '',
                    reply TEXT DEFAULT '',
                    sources TEXT DEFAULT '[]',
                    created_at TEXT
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def add(self, session_id: str, message: str, reply: str, sources: list) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO conversation_citations (session_id, message, reply, sources, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, message, reply, json.dumps(sources, ensure_ascii=False), self._now()),
            )
            self._conn.commit()
            return cur.lastrowid

    def list(self, session_id: str = "", limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM conversation_citations"
        params = []
        if session_id:
            sql += " WHERE session_id = ?"
            params.append(session_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            try:
                item["sources"] = json.loads(item.get("sources") or "[]")
            except Exception:
                item["sources"] = []
            result.append(item)
        return result


citation_manager = CitationManager()
