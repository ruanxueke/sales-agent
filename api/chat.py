"""Wechaty 消息处理 API - 接收 bot.js 转发来的微信消息"""
from __future__ import annotations
import asyncio
import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.executor import ExecutorBusy, agent_executor
from core.security import current_tenant
from core.tenancy import tenant_session_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["wechaty"])


class ChatRequest(BaseModel):
    message: str
    from_user: str = "unknown"
    room: str = ""         # 群聊 ID，空则为个人消息
    nickname: str = ""


class ChatResponse(BaseModel):
    reply: str


@router.post("/chat", response_model=ChatResponse)
async def handle_chat(req: ChatRequest, request: Request):
    """接收 Wechaty 转发的微信消息，返回 Agent 回复"""
    msg = req.message
    external_id = req.from_user or req.room
    session_id = tenant_session_key(
        "wechat",
        current_tenant(request),
        external_id,
    )

    logger.info(f"[Wechaty] from={req.from_user} room={req.room} msg={msg}")

    try:
        from core.agent import sales_agent
        future = agent_executor.submit(
            sales_agent.chat,
            msg,
            session_id,
            req.nickname or None,
            "wechat",
        )
        reply = await asyncio.wait_for(asyncio.wrap_future(future), timeout=120)
    except ExecutorBusy:
        logger.warning("[Wechaty] 任务队列已满，拒绝请求")
        reply = "当前咨询较多，请稍后再试。"
    except Exception as e:
        logger.error(f"Agent 调用失败: {e}")
        reply = "抱歉，我暂时无法处理您的问题，请稍后再试。"

    return ChatResponse(reply=reply)
