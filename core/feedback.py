"""会话标注回灌：人工标注回复质量 → 汇总待优化清单 → 回灌话术弹药库"""
from __future__ import annotations
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime
from pathlib import Path

from config.settings import settings

logger = __import__("logging").getLogger(__name__)

DB_PATH = Path(settings.DATA_DIR) / "customers.db"


class FeedbackManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT DEFAULT '',
                    customer_id INTEGER,
                    message TEXT DEFAULT '',
                    reply TEXT DEFAULT '',
                    rating TEXT DEFAULT 'bad',
                    issue_type TEXT DEFAULT '',
                    standard_reply TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    status TEXT DEFAULT 'open',
                    created_at TEXT
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def add(self, session_id="", message="", reply="", rating="bad",
            issue_type="", standard_reply="", note="", customer_id=None) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO conversation_feedback (session_id, customer_id, message, reply, rating, issue_type, standard_reply, note, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
                (session_id, customer_id, message, reply, rating, issue_type, standard_reply, note, self._now()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM conversation_feedback WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def list(self, status: str = "", limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM conversation_feedback"
        params = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update(self, item_id: int, status: str = "", standard_reply: str = "") -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM conversation_feedback WHERE id = ?", (item_id,)
            ).fetchone()
            if not row:
                return None
            sets = []
            params = []
            if status:
                sets.append("status = ?")
                params.append(status)
            if standard_reply:
                sets.append("standard_reply = ?")
                params.append(standard_reply)
            if sets:
                params.append(item_id)
                self._conn.execute(
                    "UPDATE conversation_feedback SET %s WHERE id = ?" % ", ".join(sets),
                    params,
                )
                self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM conversation_feedback WHERE id = ?", (item_id,)
            ).fetchone()
            return dict(row)

    def summary(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM conversation_feedback").fetchone()[0]
            open_count = self._conn.execute(
                "SELECT COUNT(*) FROM conversation_feedback WHERE status = 'open'"
            ).fetchone()[0]
            bad = self._conn.execute(
                "SELECT COUNT(*) FROM conversation_feedback WHERE rating = 'bad'"
            ).fetchone()[0]
            by_issue = {}
            for r in self._conn.execute(
                "SELECT issue_type, COUNT(*) AS c FROM conversation_feedback WHERE issue_type != '' GROUP BY issue_type"
            ).fetchall():
                by_issue[r["issue_type"]] = r["c"]
            by_day = {}
            for r in self._conn.execute(
                "SELECT substr(created_at, 1, 10) AS d, COUNT(*) AS c FROM conversation_feedback GROUP BY d ORDER BY d DESC LIMIT 14"
            ).fetchall():
                by_day[r["d"]] = r["c"]
        return {
            "total": total,
            "open": open_count,
            "bad": bad,
            "good": total - bad,
            "by_issue": by_issue,
            "by_day": by_day,
        }


    def backfill_to_ammo(self, item_id: int) -> dict | None:
        """把标注的标准话术回灌到跟进话术库"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM conversation_feedback WHERE id = ? AND standard_reply != ''", (item_id,)
            ).fetchone()
            if not row:
                return None
            scene = row["issue_type"] or "other"
            self._conn.execute(
                "INSERT INTO followup_scripts (followup_scene, trigger_condition, value_point, script_example, next_goal, delay_hours, active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (scene, f"标注回灌: {row['note'] or ''}", "人工标注标准回复",
                 row["standard_reply"], "按标准话术推进", 0, self._now()),
            )
            self._conn.execute(
                "UPDATE conversation_feedback SET status = 'closed' WHERE id = ?", (item_id,)
            )
            self._conn.commit()
            return {"id": item_id, "scene": scene}


feedback_manager = FeedbackManager()
