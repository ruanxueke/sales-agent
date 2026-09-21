"""会话结构化输出接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query

from core.conversation import conversation_manager
from core.security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["conversations"], dependencies=[Depends(require_api_key)])


@router.get("/conversations/summaries")
async def list_summaries(session_id: str = Query(""), status: str = Query(""), limit: int = Query(200, le=1000)):
    return {"summaries": conversation_manager.list_summaries(session_id=session_id, status=status, limit=limit)}


@router.get("/conversations/metrics")
async def list_metrics(session_id: str = Query(""), status: str = Query(""), limit: int = Query(200, le=1000)):
    return {"metrics": conversation_manager.list_metrics(session_id=session_id, status=status, limit=limit)}


@router.get("/conversations/stats")
async def conversation_stats():
    return conversation_manager.stats()
