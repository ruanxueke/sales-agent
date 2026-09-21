"""中台 API 客户端：心跳、回复、去重、任务、发送计量、审计、暂停。"""
from __future__ import annotations

import logging

import requests

from . import config

logger = logging.getLogger(__name__)


class VisionApi:
    def __init__(self, base: str = "", api_key: str = ""):
        self.base = (base or config.API_BASE).rstrip("/")
        self.api_key = api_key or config.API_KEY
        self._headers = {"Content-Type": "application/json"}
        if config.TOKEN:
            self._headers["Authorization"] = "Bearer " + config.TOKEN
        elif self.api_key:
            self._headers["X-API-Key"] = self.api_key

    def _post(self, path: str, payload: dict):
        try:
            resp = requests.post(self.base + path, headers=self._headers, json=payload, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("API %s 返回 %s: %s", path, resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("API %s 请求失败: %s", path, e)
        return {}

    def _get(self, path: str):
        try:
            resp = requests.get(self.base + path, headers=self._headers, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("API %s 返回 %s", path, resp.status_code)
        except Exception as e:
            logger.error("API %s 请求失败: %s", path, e)
        return {}

    def status(self) -> dict:
        return self._get("/api/v1/vision/status")

    def heartbeat(self, instance_id: str = "", mode: str = "", contact: str = "", detail: str = "") -> dict:
        return self._post("/api/v1/vision/heartbeat", {
            "instance_id": instance_id or config.INSTANCE_ID,
            "mode": mode or config.MODE,
            "contact": contact or "",
            "detail": detail or "",
        })

    def get_reply(self, content: str, session_id: str = "", contact: str = "", mode: str = "", instance_id: str = "") -> dict:
        data = self._post("/api/v1/vision/reply", {
            "content": content,
            "session_id": session_id or contact or "vision",
            "contact": contact or "",
            "mode": mode or config.MODE,
            "source": f"vision_{mode or config.MODE}",
            "instance_id": instance_id or config.INSTANCE_ID,
        })
        return {"ok": bool(data.get("reply")), "reply": data.get("reply") or "", "handover": bool(data.get("handover"))}

    def mark_seen(self, fingerprint: str, instance_id: str = "") -> dict:
        return self._post("/api/v1/vision/mark-seen", {"instance_id": instance_id or config.INSTANCE_ID, "fingerprint": fingerprint})

    def claim_tasks(self, limit: int = 1, mode: str = "", instance_id: str = "") -> list[dict]:
        data = self._post("/api/v1/vision/tasks/claim", {
            "instance_id": instance_id or config.INSTANCE_ID,
            "limit": max(1, int(limit)),
            "mode": mode or config.MODE,
        })
        return data.get("tasks") or []

    def complete_task(self, task_id: str, status: str, note: str = "", instance_id: str = "") -> dict:
        return self._post("/api/v1/vision/tasks/complete", {
            "task_id": task_id,
            "status": status,
            "note": note or "",
            "instance_id": instance_id or config.INSTANCE_ID,
        })

    def record_send(self, count: int = 1, instance_id: str = "") -> dict:
        return self._post("/api/v1/vision/record-send", {"count": count, "instance_id": instance_id or config.INSTANCE_ID})

    def audit(self, action: str, detail: dict, instance_id: str = "") -> dict:
        return self._post("/api/v1/vision/audit", {"action": action, "detail": detail or {}, "instance_id": instance_id or config.INSTANCE_ID})

    def pause(self, paused: bool = True, instance_id: str = "") -> dict:
        return self._post("/api/v1/vision/pause", {"paused": paused, "instance_id": instance_id or config.INSTANCE_ID})
