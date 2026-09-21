"""安全合规接口：滥用黑名单管理"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.security_layers import blocklist_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["security"], dependencies=[Depends(require_api_key)])


class BlockCreate(BaseModel):
    session_id: str
    reason: str = ""


@router.get("/security/blocklist")
async def list_blocked(limit: int = Query(100, le=1000)):
    return {"items": blocklist_manager.list(limit=limit)}


@router.post("/security/blocklist", dependencies=[Depends(require_admin)])
async def add_blocked(req: BlockCreate):
    return {"item": blocklist_manager.add(req.session_id, req.reason)}


@router.delete("/security/blocklist/{session_id}", dependencies=[Depends(require_admin)])
async def remove_blocked(session_id: str):
    return {"removed": blocklist_manager.remove(session_id)}
