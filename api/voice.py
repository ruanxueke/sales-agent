"""微信语音消息接口：语音转文字后交给销售智能体"""
from __future__ import annotations
import asyncio
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from core.executor import ExecutorBusy, agent_executor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["voice"])


@router.post("/tts")
async def tts(payload: dict):
    from core.voice_ai import voice_ai
    text = (payload.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text 必填"}
    result = voice_ai.synthesize(text)
    return {"ok": result.get("ok"), "audio_url": result.get("audio_url") or "", "error": result.get("error") or ""}


@router.post("/chat_voice")
async def chat_voice(
    file: UploadFile = File(...),
    from_user: str = Form("unknown"),
    room: str = Form(""),
    nickname: str = Form(""),
):
    tmp_path = None
    try:
        suffix = Path(file.filename or "voice.sil").suffix or ".sil"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        from core.asr import speech_to_text
        text = await asyncio.to_thread(speech_to_text.transcribe_file, tmp_path)
        logger.info(f"[Voice] from={from_user} room={room} transcript={text}")

        if not text:
            return {"reply": "抱歉，我没有听清您的语音，请再说一次或改为文字。", "transcript": ""}

        session_id = from_user or room
        from core.agent import sales_agent
        future = agent_executor.submit(
            sales_agent.chat,
            text,
            session_id,
            nickname or None,
            "wechat",
        )
        reply = await asyncio.wait_for(asyncio.wrap_future(future), timeout=120)
        # 仅当客户明确要求语音回复时才合成语音，否则正常文字回复
        voice_words = ("语音回复", "发语音", "用语音", "语音说", "语音给我", "语音回我", "语音回答")
        want_voice = any(w in text for w in voice_words)
        audio_url = ""
        emotion = "neutral"
        from core.voice_ai import voice_ai
        emotion = voice_ai.emotion(text).get("emotion") or "neutral"
        if want_voice:
            tts = voice_ai.synthesize(reply) if reply else {}
            audio_url = tts.get("audio_url") or ""
        return {
            "reply": reply,
            "transcript": text,
            "audio_url": audio_url,
            "emotion": emotion,
        }
    except ExecutorBusy:
        logger.warning("[Voice] 任务队列已满，拒绝请求")
        return {"reply": "当前咨询较多，请稍后再试。", "transcript": ""}
    except Exception as e:
        logger.error(f"[Voice] 处理失败: {e}")
        return {"reply": "抱歉，语音暂时无法处理，请稍后再试或改为文字。", "transcript": ""}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError as e:
                logger.debug("chat_voice 异常已忽略: %s", e)
