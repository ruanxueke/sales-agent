"""知识缺口收集：AI 查不到内容时自动记录客户问题，形成待补充清单"""
from __future__ import annotations
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime
from pathlib import Path

from config.settings import settings

DB_PATH = Path(settings.DATA_DIR) / "customers.db"


class KnowledgeGapManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_gaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT DEFAULT '',
                    question TEXT DEFAULT '',
                    created_at TEXT
                )
                """
            )
            try:
                self._conn.execute(
                    "ALTER TABLE knowledge_gaps ADD COLUMN tenant_id INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass
            self._conn.commit()

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def add(self, session_id: str, question: str, tenant_id: int = 0) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM knowledge_gaps WHERE tenant_id = ? AND question = ? LIMIT 1",
                (int(tenant_id or 0), question),
            ).fetchone()
            if row:
                return row["id"]
            cur = self._conn.execute(
                "INSERT INTO knowledge_gaps (tenant_id, session_id, question, created_at) VALUES (?, ?, ?, ?)",
                (int(tenant_id or 0), session_id, question, self._now()),
            )
            self._conn.commit()
            return cur.lastrowid

    def list(
        self,
        limit: int = 200,
        tenant_id: int | None = None,
    ) -> list[dict]:
        with self._lock:
            if tenant_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM knowledge_gaps ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM knowledge_gaps WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
                    (int(tenant_id), limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def count(self, tenant_id: int | None = None) -> int:
        with self._lock:
            if tenant_id is None:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM knowledge_gaps"
                ).fetchone()[0]
            return self._conn.execute(
                "SELECT COUNT(*) FROM knowledge_gaps WHERE tenant_id = ?",
                (int(tenant_id),),
            ).fetchone()[0]

    def delete(self, gap_id: int, tenant_id: int | None = None) -> bool:
        with self._lock:
            if tenant_id is None:
                cur = self._conn.execute(
                    "DELETE FROM knowledge_gaps WHERE id = ?",
                    (gap_id,),
                )
            else:
                cur = self._conn.execute(
                    "DELETE FROM knowledge_gaps WHERE id = ? AND tenant_id = ?",
                    (gap_id, int(tenant_id)),
                )
            self._conn.commit()
            return cur.rowcount > 0


knowledge_gap_manager = KnowledgeGapManager()
