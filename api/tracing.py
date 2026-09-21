"""会话引用溯源与工具调用记录接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query

from core.citations import citation_manager
from core.security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["conversations"], dependencies=[Depends(require_api_key)])


@router.get("/conversations/citations")
async def list_citations(session_id: str = Query(""), limit: int = Query(100, le=500)):
    return {"citations": citation_manager.list(session_id=session_id, limit=limit)}
