"""LLM 用量统计：记录每次调用的 token 数与耗时"""
from __future__ import annotations
import logging
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)


class UsageRecorder:
    def __init__(self, db_path: Path = None):
        self._path = str(db_path or (settings.DATA_DIR / "llm_usage.db"))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
                """
            )
            self._conn.commit()

    def record(self, session_id: str, source: str, model: str, usage: dict, latency_ms: int):
        with self._lock:
            self._conn.execute(
                "INSERT INTO llm_usage "
                "(session_id, source, model, prompt_tokens, completion_tokens, total_tokens, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    source or "unknown",
                    model or "",
                    int(usage.get("prompt_tokens") or 0),
                    int(usage.get("completion_tokens") or 0),
                    int(usage.get("total_tokens") or 0),
                    int(latency_ms or 0),
                ),
            )
            self._conn.commit()

    def daily_summary(self, days: int = 7) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day,
                       COUNT(*) AS calls,
                       SUM(prompt_tokens) AS prompt_tokens,
                       SUM(completion_tokens) AS completion_tokens,
                       SUM(total_tokens) AS total_tokens,
                       SUM(latency_ms) AS latency_ms
                FROM llm_usage
                WHERE created_at >= date('now', 'localtime', ?)
                GROUP BY day
                ORDER BY day
                """,
                (f"-{max(days - 1, 0)} days",),
            ).fetchall()
            return [dict(r) for r in rows]


usage_recorder = UsageRecorder()
