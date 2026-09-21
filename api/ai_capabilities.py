"""AI 能力 API：多模态、编排、语音状态"""
from __future__ import annotations
from fastapi import APIRouter, Depends, File, UploadFile

from core.multimodal import multimodal
from core.orchestrator import orchestrator
from core.security import require_api_key
from core.voice_ai import voice_ai
import logging
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1", tags=["ai-capabilities"], dependencies=[Depends(require_api_key)])


@router.get("/multimodal/status")
async def multimodal_status():
    return multimodal.status()


@router.post("/multimodal/analyze")
async def multimodal_analyze(file: UploadFile = File(...)):
    import os
    import tempfile
    suffix = os.path.splitext(file.filename or "")[1] or ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        return multimodal.handle_attachment(path, file.content_type or "")
    finally:
        try:
            os.unlink(path)
        except Exception as e:
            logger.debug("multimodal_analyze 异常已忽略: %s", e)


@router.get("/orchestrator/status")
async def orchestrator_status():
    return orchestrator.status()


@router.post("/orchestrator/run")
async def orchestrator_run(payload: dict):
    message = (payload.get("message") or "").strip()
    if not message:
        return {"ok": False, "error": "message 必填"}
    return orchestrator.run(message, payload.get("customer") or None)


@router.get("/voice/status")
async def voice_status():
    return voice_ai.status()
