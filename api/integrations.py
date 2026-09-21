"""集成生态 API：飞书/钉钉/ERP 状态与发送接口（配置占位）"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.integrations import send_dingtalk_message, send_feishu_message, status
from core.security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["integrations"], dependencies=[Depends(require_api_key)])


class SendModel(BaseModel):
    channel: str
    user_id: str
    content: str


@router.get("/integrations/status")
async def integrations_status():
    return status()


@router.post("/integrations/send")
async def integrations_send(req: SendModel):
    if req.channel == "feishu":
        return send_feishu_message(req.user_id, req.content)
    if req.channel == "dingtalk":
        return send_dingtalk_message(req.user_id, req.content)
    return {"ok": False, "error": f"不支持的渠道: {req.channel}"}
