"""视觉受管执行器服务端控制台：心跳、任务中心、去重、审计、风控、人工接管。

桌面 Agent 通过 API 与中台通信：上报心跳、认领主动触达任务、提交审计、暂停/恢复。
Redis 不可用时降级为本地 JSON 文件，保证单机也能跑通。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)

STATE_FILE = Path(settings.DATA_DIR) / "vision_agent_state.json"
TASKS_FILE = Path(settings.DATA_DIR) / "vision_agent_tasks.json"
SEEN_FILE = Path(settings.DATA_DIR) / "vision_agent_seen.json"
AUDIT_FILE = Path(settings.DATA_DIR) / "vision_agent_audit.jsonl"
AUDIT_MAX_BYTES = 20 * 1024 * 1024
SEEN_MAX_ITEMS = 50000
TASK_TTL_DAYS = 30


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _task_id() -> str:
    return f"vt-{int(time.time())}-{uuid.uuid4().hex[:6]}"


def _json_load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("读取 %s 失败: %s", path.name, e)
    return default


def _json_save(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("写入 %s 失败: %s", path.name, e)


class VisionAgentManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._state = {
            "enabled": False,
            "mode": "",
            "status": "offline",  # offline/idle/scanning/replying/paused/blocked
            "last_seen": "",
            "paused": False,
            "last_error": "",
            "sends_today": 0,
            "tasks_pending": 0,
            "updated_at": "",
            "instances": {},
            "human_mode_contacts": {},
        }
        self._tasks: list[dict] = []
        self._seen: set[str] = set()
        self._local_task_locks: dict[str, float] = {}
        self._load()

    def _redis(self):
        try:
            return getattr(self, "_redis_client", None) or self._connect_redis()
        except Exception:
            return None

    def _connect_redis(self):
        try:
            from core.redis_session import get_sync_redis
            client = get_sync_redis()
            self._redis_client = client
            return client
        except Exception:
            return None

    def _load(self):
        with self._lock:
            data = _json_load(STATE_FILE, {})
            if isinstance(data, dict):
                self._state.update(data)
                self._state.setdefault("instances", {})
                self._state.setdefault("human_mode_contacts", {})
            tasks = _json_load(TASKS_FILE, [])
            if isinstance(tasks, list):
                self._tasks = tasks
            seen = _json_load(SEEN_FILE, [])
            if isinstance(seen, list):
                self._seen = set(seen[-SEEN_MAX_ITEMS:])
            self._prune_tasks()

    def _save(self):
        with self._lock:
            self._state["updated_at"] = _now()
            self._state["enabled"] = bool(settings.VISION_AGENT_ENABLED)
            self._state["mode"] = settings.VISION_AGENT_MODE or ""
            _json_save(STATE_FILE, self._state)
            _json_save(TASKS_FILE, self._tasks[-2000:])
            _json_save(SEEN_FILE, sorted(self._seen)[-SEEN_MAX_ITEMS:])

    def _prune_tasks(self):
        cutoff = time.time() - TASK_TTL_DAYS * 86400
        kept = []
        for t in self._tasks:
            try:
                created = t.get("created_ts") or 0
                if created and created < cutoff and t.get("status") in ("sent", "failed", "cancelled", "skipped"):
                    continue
            except Exception as e:
                logger.debug("VisionAgentManager._prune_tasks 异常已忽略: %s", e)
            kept.append(t)
        if len(kept) != len(self._tasks):
            self._tasks = kept

    # ===== 状态与心跳 =====

    def status(self) -> dict:
        with self._lock:
            self._state["enabled"] = bool(settings.VISION_AGENT_ENABLED)
            self._state["mode"] = settings.VISION_AGENT_MODE or ""
            r = self._redis()
            if r is not None:
                online = r.get("vision:agent:last_seen") or ""
                if online:
                    self._state["last_seen"] = online
                paused = r.get("vision:agent:paused")
                if paused is not None:
                    self._state["paused"] = bool(int(paused))
                sends = r.get("vision:agent:sends_today")
                if sends is not None:
                    self._state["sends_today"] = int(sends)
            instances = dict(self._state.get("instances") or {})
            for inst_id, inst in instances.items():
                inst = dict(inst)
                if r is not None:
                    key = f"vision:agent:last_seen:{inst_id}"
                    seen = r.get(key) or ""
                    if seen:
                        inst["last_seen"] = seen
                    pause_key = f"vision:agent:paused:{inst_id}"
                    paused_val = r.get(pause_key)
                    if paused_val is not None:
                        inst["paused"] = bool(int(paused_val))
                instances[inst_id] = inst
            pending = sum(1 for t in self._tasks if t.get("status") == "pending")
            result = dict(self._state)
            result["instances"] = instances
            result["tasks_pending"] = pending
            result["daily_limit"] = int(settings.VISION_AGENT_MAX_SENDS_PER_DAY or 300)
            result["poll_interval"] = int(settings.VISION_AGENT_POLL_INTERVAL or 2)
            result["model"] = settings.VISION_MODEL or ""
            result["monitor"] = settings.VISION_AGENT_MONITOR or ""
            result["human_mode_contacts"] = dict(self._state.get("human_mode_contacts") or {})
            return result

    def heartbeat(self, instance_id: str = "", mode: str = "", detail: str = "", contact: str = "") -> dict:
        inst_id = instance_id or "default"
        now = _now()
        r = self._redis()
        with self._lock:
            instances = self._state.setdefault("instances", {})
            inst = dict(instances.get(inst_id) or {})
            inst.update({
                "id": inst_id,
                "mode": mode or settings.VISION_AGENT_MODE or "",
                "status": "idle",
                "last_seen": now,
                "contact": contact or inst.get("contact") or "",
                "detail": detail or "",
                "last_error": detail or "",
                "updated_at": now,
            })
            instances[inst_id] = inst
            self._state["status"] = "idle"
            self._state["last_seen"] = now
            self._state["mode"] = inst["mode"]
            self._state["last_error"] = detail or ""
            self._save()
        if r is not None:
            r.set("vision:agent:last_seen", now)
            r.set(f"vision:agent:last_seen:{inst_id}", now)
            r.set("vision:agent:mode", inst["mode"])
        return {"ok": True, "time": now, "instance_id": inst_id}

    def set_paused(self, paused: bool, instance_id: str = "") -> dict:
        r = self._redis()
        with self._lock:
            if instance_id:
                instances = self._state.setdefault("instances", {})
                inst = dict(instances.get(instance_id) or {})
                inst["paused"] = bool(paused)
                inst["status"] = "paused" if paused else "idle"
                inst["updated_at"] = _now()
                instances[instance_id] = inst
            else:
                self._state["paused"] = bool(paused)
                self._state["status"] = "paused" if paused else "idle"
            self._save()
        if r is not None:
            if instance_id:
                r.set(f"vision:agent:paused:{instance_id}", "1" if paused else "0")
            else:
                r.set("vision:agent:paused", "1" if paused else "0")
        return {"ok": True, "paused": bool(paused), "instance_id": instance_id or "global"}

    def record_send(self, count: int = 1, instance_id: str = "") -> dict:
        count = max(1, int(count))
        limit = int(settings.VISION_AGENT_MAX_SENDS_PER_DAY or 300)
        r = self._redis()
        with self._lock:
            if instance_id:
                instances = self._state.setdefault("instances", {})
                inst = dict(instances.get(instance_id) or {})
                inst["sends_today"] = int(inst.get("sends_today") or 0) + count
                inst["updated_at"] = _now()
                instances[instance_id] = inst
            self._state["sends_today"] = int(self._state.get("sends_today") or 0) + count
            total = self._state["sends_today"]
            blocked = total >= limit
            if blocked and not self._state.get("paused"):
                self._state["paused"] = True
                self._state["status"] = "paused"
                self._state["last_error"] = f"今日发送量已达上限 {limit}"
            self._save()
        if r is not None:
            total = r.incrby("vision:agent:sends_today", count)
            r.expire("vision:agent:sends_today", 86400)
            if instance_id:
                key = f"vision:agent:sends_today:{instance_id}"
                r.incrby(key, count)
                r.expire(key, 86400)
            blocked = int(total) >= limit
            if blocked:
                r.set("vision:agent:paused", "1")
        else:
            total = self._state["sends_today"]
            blocked = total >= limit
        return {"ok": True, "sends_today": int(total), "limit": limit, "blocked": blocked}

    # ===== 消息去重 =====

    def mark_seen(self, instance_id: str, fingerprint: str) -> dict:
        fingerprint = (fingerprint or "").strip()
        if not fingerprint:
            return {"ok": False, "error": "缺少消息指纹"}
        r = self._redis()
        if r is not None:
            key = f"vision:seen:{instance_id or 'default'}"
            if r.sismember(key, fingerprint):
                return {"ok": True, "was_new": False}
            r.sadd(key, fingerprint)
            r.expire(key, 7 * 86400)
            return {"ok": True, "was_new": True}
        with self._lock:
            if fingerprint in self._seen:
                return {"ok": True, "was_new": False}
            self._seen.add(fingerprint)
            if len(self._seen) > SEEN_MAX_ITEMS:
                self._seen = set(sorted(self._seen)[-SEEN_MAX_ITEMS:])
            self._save()
            return {"ok": True, "was_new": True}

    # ===== 人工接管 =====

    def mark_human_mode(self, instance_id: str, contact: str, active: bool = True) -> dict:
        contact = (contact or "").strip()
        if not contact:
            return {"ok": False, "error": "缺少联系人"}
        with self._lock:
            contacts = self._state.setdefault("human_mode_contacts", {})
            key = f"{instance_id or 'default'}::{contact}"
            if active:
                contacts[key] = {"time": _now(), "instance_id": instance_id or "default", "contact": contact}
            else:
                contacts.pop(key, None)
            self._save()
        return {"ok": True, "contact": contact, "human_mode": bool(active)}

    def is_human_mode(self, instance_id: str, contact: str) -> bool:
        key = f"{instance_id or 'default'}::{contact}"
        with self._lock:
            return key in (self._state.get("human_mode_contacts") or {})

    # ===== 主动触达任务 =====

    def create_task(
        self,
        mode: str,
        contact: str,
        content: str,
        instance_id: str = "",
        scheduled_at: str = "",
        priority: int = 0,
    ) -> dict:
        contact = (contact or "").strip()
        content = (content or "").strip()
        if not contact or not content:
            return {"ok": False, "error": "联系人与内容不能为空"}
        if len(content) > 2000:
            return {"ok": False, "error": "单条内容不能超过 2000 字"}
        task = {
            "id": _task_id(),
            "mode": mode or settings.VISION_AGENT_MODE or "wecom",
            "instance_id": instance_id or "",
            "contact": contact,
            "content": content,
            "status": "pending",
            "scheduled_at": scheduled_at or "",
            "priority": max(0, int(priority or 0)),
            "created_at": _now(),
            "created_ts": time.time(),
            "sent_at": "",
            "note": "",
        }
        with self._lock:
            self._tasks.append(task)
            self._save()
        self.audit("task_create", {"task_id": task["id"], "contact": contact, "mode": task["mode"]}, instance_id)
        return {"ok": True, "task": task}

    def list_tasks(self, instance_id: str = "", mode: str = "", status: str = "", limit: int = 100) -> list[dict]:
        with self._lock:
            items = list(self._tasks)
        items.sort(key=lambda t: (t.get("priority") or 0, t.get("created_ts") or 0), reverse=True)
        result = []
        for t in items:
            if instance_id and t.get("instance_id") and t.get("instance_id") != instance_id:
                continue
            if mode and t.get("mode") != mode:
                continue
            if status and t.get("status") != status:
                continue
            result.append(t)
            if len(result) >= max(1, int(limit or 100)):
                break
        return result

    def claim_tasks(self, instance_id: str = "", limit: int = 1, mode: str = "") -> list[dict]:
        inst_id = instance_id or "default"
        r = self._redis()
        with self._lock:
            candidates = []
            for t in self._tasks:
                if t.get("status") != "pending":
                    continue
                if mode and t.get("mode") != mode:
                    continue
                if t.get("instance_id") and t.get("instance_id") != inst_id:
                    continue
                scheduled = t.get("scheduled_at") or ""
                if scheduled:
                    try:
                        scheduled_ts = datetime.strptime(scheduled, "%Y-%m-%d %H:%M:%S").timestamp()
                        if scheduled_ts > time.time():
                            continue
                    except Exception as e:
                        logger.warning("解析任务调度时间失败，该任务会被立即领取执行: %s", e)
                candidates.append(t)
            candidates.sort(key=lambda t: (t.get("priority") or 0, t.get("created_ts") or 0), reverse=True)
            claimed = []
            for task in candidates:
                if len(claimed) >= max(1, int(limit or 1)):
                    break
                lock_key = f"vision:task:lock:{task['id']}"
                got_lock = False
                if r is not None:
                    try:
                        got_lock = bool(r.set(lock_key, inst_id, nx=True, ex=600))
                    except Exception:
                        got_lock = False
                if not got_lock:
                    now = time.time()
                    prev = self._local_task_locks.get(task["id"]) or 0
                    if now - prev < 300:
                        continue
                    self._local_task_locks[task["id"]] = now
                    got_lock = True
                task["status"] = "running"
                task["assigned_to"] = inst_id
                task["claimed_at"] = _now()
                claimed.append(task)
            if claimed:
                self._save()
        for task in claimed:
            self.audit("task_claim", {"task_id": task["id"], "contact": task["contact"]}, inst_id)
        return claimed

    def complete_task(self, task_id: str, status: str, note: str = "", instance_id: str = "") -> dict:
        status = status if status in ("sent", "failed", "cancelled", "skipped") else "failed"
        with self._lock:
            for t in self._tasks:
                if t.get("id") == task_id:
                    t["status"] = status
                    t["sent_at"] = _now() if status == "sent" else t.get("sent_at") or ""
                    t["note"] = (note or "")[:500]
                    t["updated_at"] = _now()
                    self._save()
                    self.audit("task_complete", {"task_id": task_id, "status": status, "note": t["note"]}, instance_id)
                    return {"ok": True, "task": t}
        return {"ok": False, "error": "任务不存在"}

    def cancel_task(self, task_id: str) -> dict:
        return self.complete_task(task_id, "cancelled", note="管理员取消")

    # ===== 审计 =====

    def audit(self, action: str, detail: dict, instance_id: str = "") -> dict:
        record = {
            "time": _now(),
            "ts": time.time(),
            "action": action,
            "instance_id": instance_id or "",
            "mode": settings.VISION_AGENT_MODE or "",
            "detail": detail or {},
        }
        try:
            AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > AUDIT_MAX_BYTES:
                rotated = AUDIT_FILE.with_suffix(".1.jsonl")
                if rotated.exists():
                    rotated.unlink(missing_ok=True)
                AUDIT_FILE.rename(rotated)
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("视觉执行器审计写入失败: %s", e)
        return {"ok": True}

    def list_audit(self, limit: int = 100, instance_id: str = "", action: str = "", since_ts: float = 0) -> list[dict]:
        records = []
        try:
            if AUDIT_FILE.exists():
                lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
                for line in lines[-5000:]:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if instance_id and rec.get("instance_id") != instance_id:
                        continue
                    if action and rec.get("action") != action:
                        continue
                    if since_ts and (rec.get("ts") or 0) < since_ts:
                        continue
                    records.append(rec)
        except Exception as e:
            logger.warning("视觉执行器审计读取失败: %s", e)
        records.sort(key=lambda r: r.get("ts") or 0, reverse=True)
        return records[: max(1, int(limit or 100))]

    # ===== 回复与风控 =====

    def reply(self, content: str, session_id: str = "", contact: str = "", mode: str = "", source: str = "", instance_id: str = "") -> dict:
        content = (content or "").strip()
        if not content:
            return {"ok": False, "error": "消息内容为空"}
        if not settings.VISION_AGENT_ENABLED:
            return {"ok": False, "error": "视觉执行器未启用，请先开启 VISION_AGENT_ENABLED"}
        contact = contact or session_id or ""
        session_id = session_id or contact or "vision"
        source = source or f"vision_{mode or 'channel'}"
        from core.agent import sales_agent
        reply = sales_agent.chat(content, session_id=session_id, nickname=contact or "", source=source)
        reply = (reply or "").strip()
        handover = False
        if contact:
            handover = self._detect_handover(content)
            if handover:
                self.mark_human_mode(instance_id or "default", contact, True)
        return {
            "ok": True,
            "reply": reply,
            "handover": handover,
            "session_id": session_id,
            "contact": contact,
        }

    def _detect_handover(self, content: str) -> bool:
        from core.handover_words import contains_handover_keyword
        return contains_handover_keyword(content, "vision")

    def alert(self, message: str):
        try:
            from core.alerting import alert_manager
            alert_manager.push_alert("vision_agent", message)
        except Exception as e:
            logger.warning("视觉执行器告警失败: %s", e)


vision_agent = VisionAgentManager()
