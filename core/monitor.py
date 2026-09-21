"""运行监控：QPS、延迟、错误率、机器人在线状态"""
from __future__ import annotations
import logging
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, db_path: Path = None):
        self._path = str(db_path or (settings.DATA_DIR / "metrics.db"))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    endpoint TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
                CREATE TABLE IF NOT EXISTS heartbeats (
                    source TEXT PRIMARY KEY,
                    last_seen TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def record_api_event(self, endpoint: str, latency_ms: int, success: bool):
        with self._lock:
            self._conn.execute(
                "INSERT INTO api_events (endpoint, latency_ms, success) VALUES (?, ?, ?)",
                (endpoint, int(latency_ms), 1 if success else 0),
            )
            self._conn.commit()

    def heartbeat(self, source: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._conn.execute(
                "INSERT INTO heartbeats (source, last_seen) VALUES (?, ?) "
                "ON CONFLICT(source) DO UPDATE SET last_seen = excluded.last_seen",
                (source, now),
            )
            self._conn.commit()

    def summary(self, window_seconds: int = 300) -> dict:
        cutoff = (datetime.now() - timedelta(seconds=window_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM api_events WHERE created_at >= ?", (cutoff,)
            ).fetchall()
            total = len(rows)
            errors = sum(1 for r in rows if r["success"] == 0)
            latencies = sorted(r["latency_ms"] for r in rows)
            avg = round(sum(latencies) / len(latencies), 1) if latencies else 0
            p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)] if latencies else 0
            by_endpoint = {}
            for r in rows:
                ep = by_endpoint.setdefault(r["endpoint"], {"calls": 0, "errors": 0})
                ep["calls"] += 1
                ep["errors"] += 0 if r["success"] else 1
            bots = {}
            for h in self._conn.execute("SELECT * FROM heartbeats").fetchall():
                bots[h["source"]] = h["last_seen"]

        now = datetime.now()
        online = {}
        for src, seen in bots.items():
            try:
                dt = datetime.strptime(seen, "%Y-%m-%d %H:%M:%S")
                online[src] = (now - dt).total_seconds() < 90
            except ValueError:
                online[src] = False

        return {
            "window_seconds": window_seconds,
            "total_requests": total,
            "qps": round(total / window_seconds, 3) if window_seconds else 0,
            "avg_latency_ms": avg,
            "p95_latency_ms": p95,
            "error_count": errors,
            "error_rate": round(errors / total * 100, 2) if total else 0.0,
            "by_endpoint": by_endpoint,
            "bots": online,
        }


monitor = Monitor()
