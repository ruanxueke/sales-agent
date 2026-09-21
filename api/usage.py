"""LLM 用量统计查询接口"""
from __future__ import annotations
from fastapi import APIRouter

from core.usage import usage_recorder

router = APIRouter(prefix="/api/v1", tags=["usage"])


@router.get("/usage/summary")
async def usage_summary(days: int = 7):
    return {"summary": usage_recorder.daily_summary(days)}
