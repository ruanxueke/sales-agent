"""微信图片消息接口：MIMO 视觉模型读图 → 转成文字描述 → DeepSeek 生成销售回复"""
from __future__ import annotations
import asyncio
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile

from core.executor import ExecutorBusy, agent_executor
from core.multimodal import multimodal
from core.security import current_tenant
from core.tenancy import tenant_session_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["image"])


@router.post("/chat_image")
async def chat_image(
    request: Request,
    file: UploadFile = File(...),
    from_user: str = Form("unknown"),
    room: str = Form(""),
    nickname: str = Form(""),
):
    tmp_path = None
    try:
        suffix = Path(file.filename or "image.jpg").suffix or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        result = multimodal.describe_image(tmp_path)
        transcript = result.get("transcript") or ""
        logger.info(f"[Image] from={from_user} room={room} mode={result.get('mode')} transcript={transcript[:100]}")

        if not transcript:
            return {
                "reply": "抱歉，图片暂时无法识别，您可以发文字描述一下，我马上帮您处理。",
                "transcript": "",
                "vision_error": result.get("error") or "",
            }

        session_id = tenant_session_key(
            "wechat",
            current_tenant(request),
            from_user or room,
        )
        from core.agent import sales_agent
        # 把图片描述作为客户消息交给 DeepSeek，回复仍由销售大脑生成
        future = agent_executor.submit(
            sales_agent.chat,
            f"[客户发送了一张图片，图片内容为：{transcript}]",
            session_id,
            nickname or None,
            "wechat",
        )
        reply = await asyncio.wait_for(asyncio.wrap_future(future), timeout=120)
        return {"reply": reply, "transcript": transcript}
    except ExecutorBusy:
        logger.warning("[Image] 任务队列已满，拒绝请求")
        return {"reply": "当前咨询较多，请稍后再试。", "transcript": ""}
    except Exception as e:
        logger.error(f"[Image] 处理失败: {e}")
        return {"reply": "抱歉，图片暂时无法处理，请稍后再试。", "transcript": ""}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError as e:
                logger.debug("chat_image 异常已忽略: %s", e)
