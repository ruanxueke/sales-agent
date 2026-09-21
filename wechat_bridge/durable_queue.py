"""Durable local queue for message upload and reply task execution."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DurableQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS outbox_events (
                    message_id TEXT PRIMARY KEY,
                    event_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_queue (
                    task_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_stage TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    diagnostic_path TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_outbox_due
                    ON outbox_events(status, next_attempt_at);
                CREATE INDEX IF NOT EXISTS ix_task_due
                    ON task_queue(status, next_attempt_at);
                """
            )

    def put_event(self, event: dict) -> None:
        message_id = str(event.get("message_id") or "").strip()
        if not message_id:
            return
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO outbox_events
                    (message_id, event_json, status, created_at, updated_at)
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (message_id, json.dumps(event, ensure_ascii=False), now, now),
            )

    def pending_events(self, limit: int = 20) -> list[dict]:
        now = _now()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM outbox_events
                WHERE status = 'pending'
                  AND (next_attempt_at = '' OR next_attempt_at <= ?)
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (now, max(1, int(limit))),
            ).fetchall()
        return [
            {
                "message_id": row["message_id"],
                "event": json.loads(row["event_json"]),
                "attempt_count": int(row["attempt_count"] or 0),
            }
            for row in rows
        ]

    def complete_event(self, message_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE outbox_events
                SET status = 'completed', last_error = '', updated_at = ?
                WHERE message_id = ?
                """,
                (_now(), message_id),
            )

    def fail_event(self, message_id: str, error: str) -> None:
        now = datetime.now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT attempt_count FROM outbox_events WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            attempts = int((row["attempt_count"] if row else 0) or 0) + 1
            delay = min(300, 2 ** min(attempts, 8))
            connection.execute(
                """
                UPDATE outbox_events
                SET attempt_count = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE message_id = ?
                """,
                (
                    attempts,
                    (now + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S"),
                    str(error or "")[:1000],
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    message_id,
                ),
            )

    def put_task(self, task: dict) -> None:
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            return
        now = _now()
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT status FROM task_queue WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if existing:
                if existing["status"] in {"completed", "manual_review", "dead_letter"}:
                    return
                connection.execute(
                    """
                    UPDATE task_queue
                    SET payload_json = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (json.dumps(task, ensure_ascii=False), now, task_id),
                )
                return
            connection.execute(
                """
                INSERT INTO task_queue
                    (task_id, payload_json, status, updated_at)
                VALUES (?, ?, 'pending', ?)
                """,
                (task_id, json.dumps(task, ensure_ascii=False), now),
            )

    def get_task(self, task_id: str) -> dict | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_queue WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if not row:
            return None
        return {
            **json.loads(row["payload_json"]),
            "local_status": row["status"],
            "last_stage": row["last_stage"],
            "local_attempt_count": int(row["attempt_count"] or 0),
            "next_attempt_at": row["next_attempt_at"],
            "last_error": row["last_error"],
            "diagnostic_path": row["diagnostic_path"],
        }

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        attempt_count: int | None = None,
        next_attempt_at: str | None = None,
        error: str | None = None,
        diagnostic_path: str | None = None,
    ) -> None:
        fields = ["updated_at = ?"]
        values: list = [_now()]
        for column, value in (
            ("status", status),
            ("last_stage", stage),
            ("attempt_count", attempt_count),
            ("next_attempt_at", next_attempt_at),
            ("last_error", error),
            ("diagnostic_path", diagnostic_path),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value)
        values.append(task_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE task_queue SET {', '.join(fields)} WHERE task_id = ?",
                values,
            )

    def recoverable_tasks(self, limit: int = 20) -> list[dict]:
        now = _now()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_queue
                WHERE status IN ('processing', 'awaiting_receipt', 'retry_wait')
                  AND (next_attempt_at = '' OR next_attempt_at <= ?)
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (now, max(1, int(limit))),
            ).fetchall()
        return [
            {
                **json.loads(row["payload_json"]),
                "local_status": row["status"],
                "last_stage": row["last_stage"],
                "local_attempt_count": int(row["attempt_count"] or 0),
                "next_attempt_at": row["next_attempt_at"],
                "last_error": row["last_error"],
                "diagnostic_path": row["diagnostic_path"],
            }
            for row in rows
        ]

    def metrics(self) -> dict:
        with self._lock, self._connect() as connection:
            event_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM outbox_events GROUP BY status"
            ).fetchall()
            task_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM task_queue GROUP BY status"
            ).fetchall()
        return {
            "events": {row["status"]: int(row["count"]) for row in event_rows},
            "tasks": {row["status"]: int(row["count"]) for row in task_rows},
        }
