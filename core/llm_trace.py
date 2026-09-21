"""LLM 调用追踪：会话、模型、耗时、Token、成本估算"""
from __future__ import annotations
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime
from pathlib import Path

from config.settings import settings

DB_PATH = Path(settings.DATA_DIR) / "customers.db"

# 每百万 token 成本（元），按模型粗略估算
COST_PER_MILLION = {
    "deepseek-chat": {"input": 2.0, "output": 8.0},
    "qwen-plus": {"input": 4.0, "output": 12.0},
}


class LLMTraceManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    message TEXT DEFAULT '',
                    reply TEXT DEFAULT '',
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0,
                    cost_yuan REAL DEFAULT 0,
                    created_at TEXT
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        cost = COST_PER_MILLION.get(model or "", {"input": 2.0, "output": 8.0})
        return round(
            (prompt_tokens / 1_000_000) * cost["input"]
            + (completion_tokens / 1_000_000) * cost["output"],
            6,
        )

    def add(self, session_id="", model="", message="", reply="",
            prompt_tokens=0, completion_tokens=0, latency_ms=0) -> dict:
        cost = self.estimate_cost(model, prompt_tokens, completion_tokens)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO llm_traces (session_id, model, message, reply, prompt_tokens, completion_tokens, latency_ms, cost_yuan, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, model, message, reply, prompt_tokens, completion_tokens,
                 int(latency_ms), cost, self._now()),
            )
            self._conn.commit()
            return {"id": cur.lastrowid, "cost_yuan": cost}

    def list(self, session_id="", limit=100) -> list[dict]:
        sql = "SELECT * FROM llm_traces"
        params = []
        if session_id:
            sql += " WHERE session_id = ?"
            params.append(session_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def summary(self, limit=5000) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM llm_traces ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        total_tokens = sum((r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0) for r in rows)
        total_cost = round(sum(r["cost_yuan"] or 0 for r in rows), 4)
        avg_latency = round(sum(r["latency_ms"] or 0 for r in rows) / len(rows), 1) if rows else 0
        return {
            "traces": len(rows),
            "total_tokens": total_tokens,
            "total_cost_yuan": total_cost,
            "avg_latency_ms": avg_latency,
        }


llm_trace_manager = LLMTraceManager()
