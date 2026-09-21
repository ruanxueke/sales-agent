"""本地桥接状态与审计。"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
import logging
logger = logging.getLogger(__name__)



def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class LocalState:
    def __init__(self, path: str | Path, ttl_days: int = 30):
        self.path = Path(path)
        self.ttl_days = ttl_days
        self._lock = threading.RLock()
        self._data = {
            "seen_messages": {},
            "tasks": {},
            "targets": {},
            "counters": {},
        }
        self._load()

    def _load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        self._data.update(raw)
                except (OSError, ValueError) as e:
                    logger.debug("LocalState._load 异常已忽略: %s", e)
            self._prune()
            self._save()

    def _prune(self) -> None:
        cutoff = datetime.now() - timedelta(days=self.ttl_days)
        for key_name in ("seen_messages", "tasks"):
            values = self._data.setdefault(key_name, {})
            self._data[key_name] = {
                key: value
                for key, value in values.items()
                if self._parse_time(value) is None or self._parse_time(value) >= cutoff
            }

    @staticmethod
    def _parse_time(value) -> datetime | None:
        if isinstance(value, dict):
            value = value.get("time") or ""
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def seen_message(self, key: str) -> bool:
        with self._lock:
            return key in self._data.setdefault("seen_messages", {})

    def mark_message(self, key: str) -> None:
        with self._lock:
            self._data.setdefault("seen_messages", {})[key] = _now()
            self._prune()
            self._save()

    def task_status(self, task_id: str) -> str:
        with self._lock:
            record = self._data.setdefault("tasks", {}).get(task_id) or {}
            if isinstance(record, dict):
                return str(record.get("status") or "")
            return ""

    def mark_task(self, task_id: str, status: str) -> None:
        with self._lock:
            self._data.setdefault("tasks", {})[task_id] = {
                "time": _now(),
                "status": status,
            }
            self._prune()
            self._save()

    def target_initialized(self, target_key: str) -> bool:
        with self._lock:
            return bool(self._data.setdefault("targets", {}).get(target_key))

    def mark_target_initialized(self, target_key: str) -> None:
        with self._lock:
            self._data.setdefault("targets", {})[target_key] = _now()
            self._save()

    def allow_send(self, target_key: str, daily_limit: int, hourly_limit: int) -> tuple[bool, str]:
        now = datetime.now()
        counters = self._data.setdefault("counters", {})
        day_key = f"{target_key}:day:{now.strftime('%Y-%m-%d')}"
        hour_key = f"{target_key}:hour:{now.strftime('%Y-%m-%d-%H')}"
        day_count = int(counters.get(day_key) or 0)
        hour_count = int(counters.get(hour_key) or 0)
        if daily_limit > 0 and day_count >= daily_limit:
            return False, f"目标今日发送已达上限 {daily_limit}"
        if hourly_limit > 0 and hour_count >= hourly_limit:
            return False, f"目标每小时发送已达上限 {hourly_limit}"
        return True, ""

    def record_send(self, target_key: str) -> None:
        now = datetime.now()
        with self._lock:
            counters = self._data.setdefault("counters", {})
            day_key = f"{target_key}:day:{now.strftime('%Y-%m-%d')}"
            hour_key = f"{target_key}:hour:{now.strftime('%Y-%m-%d-%H')}"
            counters[day_key] = int(counters.get(day_key) or 0) + 1
            counters[hour_key] = int(counters.get(hour_key) or 0) + 1
            self._prune()
            self._save()


class AuditLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def log(self, action: str, **detail) -> None:
        record = {"time": _now(), "action": action, **detail}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
