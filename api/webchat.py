"""网页客服与开放平台 API：会话接入、Webhook 注册与投递、嵌入脚本说明"""
from __future__ import annotations
import hashlib
import hmac
import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from config.settings import settings
from core.security import require_api_key
from core.webchat import webchat
import logging
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1", tags=["webchat-open"], dependencies=[Depends(require_api_key)])

WEBHOOK_DB = Path(settings.DATA_DIR) / "webhook_subscriptions.json"


def _load_hooks() -> dict:
    try:
        if WEBHOOK_DB.exists():
            return json.loads(WEBHOOK_DB.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Webhook 配置读取失败，本次不会投递任何事件: %s", e)
    return {}


def _save_hooks(hooks: dict):
    WEBHOOK_DB.write_text(json.dumps(hooks, ensure_ascii=False, indent=2), encoding="utf-8")


class HookCreate(BaseModel):
    url: str
    events: list[str] = ["customer.created", "order.paid", "chat.received"]


class WebChatStart(BaseModel):
    visitor_name: str = ""
    source_page: str = ""


@router.get("/webchat/script")
async def webchat_script():
    """返回一段可嵌入任意网页的聊天脚本占位；后端复用 /api/v1/chat"""
    script = """
/* 网页客服占位脚本：接入后可将消息 POST 到 /api/v1/chat，session 使用 webchat-{visitor_id} */
window.SalesWebChat = window.SalesWebChat || {
  init: function (opts) { console.log('SalesWebChat ready', opts || {}); },
  send: function (text, sessionKey) { return fetch('/api/v1/chat', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ message: text, from_user: sessionKey || 'webchat-visitor', source: 'webchat' }) }).then(r => r.json()); }
};
"""
    return PlainTextResponse(script, media_type="application/javascript")


@router.post("/webchat/sessions")
async def create_session(req: WebChatStart):
    return {"ok": True, "session": webchat.create_session(req.visitor_name, req.source_page)}


@router.get("/webchat/sessions")
async def list_sessions(status: str = ""):
    return {"items": webchat.list_sessions(status)}


@router.get("/webchat/sessions/{key}/messages")
async def session_messages(key: str):
    return {"items": webchat.messages(key)}


@router.post("/webchat/sessions/{key}/messages")
async def append_session_message(key: str, payload: dict):
    role = payload.get("role") or "customer"
    content = payload.get("content") or ""
    if not content:
        return {"ok": False, "error": "content 必填"}
    return {"ok": webchat.append_message(key, role, content)}


# ===== 开放平台 Webhook =====

def _sign(payload: dict, secret: str) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()


@router.get("/webhooks")
async def list_hooks():
    return {"items": list(_load_hooks().values())}


@router.post("/webhooks")
async def create_hook(req: HookCreate):
    hooks = _load_hooks()
    hook_id = "hook_" + uuid.uuid4().hex[:10]
    hooks[hook_id] = {"id": hook_id, "url": req.url, "events": req.events, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _save_hooks(hooks)
    return {"ok": True, "hook": hooks[hook_id]}


@router.delete("/webhooks/{hook_id}")
async def delete_hook(hook_id: str):
    hooks = _load_hooks()
    existed = hook_id in hooks
    hooks.pop(hook_id, None)
    _save_hooks(hooks)
    return {"ok": existed}


def dispatch_event(event: str, payload: dict):
    """供业务代码调用：事件投递到订阅的 Webhook（含签名头、重试、投递日志）"""
    import requests
    hooks = _load_hooks()
    for h in hooks.values():
        if event not in (h.get("events") or []):
            continue
        secret = settings.WEBHOOK_SECRET
        body = {"event": event, "payload": payload, "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Webhook-Signature"] = _sign(body, secret)
        status = "pending"
        error = ""
        for attempt in range(3):
            try:
                resp = requests.post(h["url"], json=body, headers=headers, timeout=8)
                if resp.status_code < 500:
                    status = "sent" if resp.ok else "http_" + str(resp.status_code)
                    if resp.ok:
                        break
                    error = resp.text[:200]
                else:
                    error = f"HTTP {resp.status_code}"
            except Exception as e:
                error = str(e)[:200]
            import time as _time
            _time.sleep(1 + attempt)
        # 投递日志
        try:
            log_dir = settings.DATA_DIR / "webhook_deliveries"
            log_dir.mkdir(parents=True, exist_ok=True)
            import json as _json
            with open(log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl", "a", encoding="utf-8") as f:
                f.write(_json.dumps({
                    "event": event, "url": h["url"], "status": status,
                    "error": error, "sent_at": body["sent_at"],
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Webhook 投递日志写入失败: %s", e)
