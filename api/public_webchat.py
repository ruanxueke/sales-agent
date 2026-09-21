"""网页客服访客通道：匿名创建会话、发消息、取回复（可嵌入任意网页）"""
from __future__ import annotations
import asyncio
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from core.executor import ExecutorBusy, agent_executor
from core.webchat import webchat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/webchat", tags=["public-webchat"])


class StartModel(BaseModel):
    visitor_name: str = ""
    source_page: str = ""


class MessageModel(BaseModel):
    session_key: str
    message: str
    nickname: str = ""


@router.post("/session")
async def start_session(req: StartModel, request: Request):
    if not settings.PUBLIC_WEBCHAT_ENABLED:
        return {"ok": False, "error": "网页客服未启用"}
    ip = _client_ip(request)
    if not _check_rate(f"wc-create:{ip}", settings.PUBLIC_WEBCHAT_MAX_SESSIONS_PER_IP, 3600):
        return {"ok": False, "error": "会话创建过于频繁，请稍后再试"}
    session = webchat.create_session(req.visitor_name, req.source_page)
    return {"ok": True, "session_key": session["session_key"]}


@router.post("/message")
async def send_message(req: MessageModel, request: Request):
    if not settings.PUBLIC_WEBCHAT_ENABLED:
        return {"ok": False, "error": "网页客服未启用"}
    ip = _client_ip(request)
    if not _check_rate(f"wc-msg:{ip}", settings.PUBLIC_WEBCHAT_RATE_LIMIT, settings.PUBLIC_WEBCHAT_RATE_WINDOW):
        return {"ok": False, "error": "消息发送过于频繁，请稍后再试"}
    text = (req.message or "").strip()
    if not text:
        return {"ok": False, "error": "消息不能为空"}
    session = webchat.get_session(req.session_key)
    if not session:
        return {"ok": False, "error": "会话不存在"}
    webchat.append_message(req.session_key, "customer", text)
    session_id = f"webchat-{req.session_key}"
    try:
        from core.agent import sales_agent
        future = agent_executor.submit(
            sales_agent.chat,
            text,
            session_id,
            req.nickname or req.session_key,
            "webchat",
        )
        reply = await asyncio.wait_for(asyncio.wrap_future(future), timeout=120)
    except ExecutorBusy:
        reply = "当前咨询较多，请稍后再试。"
    except Exception:
        reply = "抱歉，我暂时无法处理您的问题，请稍后再试。"
    webchat.append_message(req.session_key, "agent", reply)
    return {"ok": True, "reply": reply}


@router.get("/messages")
async def messages(session_key: str):
    return {"items": webchat.messages(session_key)}
