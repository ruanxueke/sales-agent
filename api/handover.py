"""转人工接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.handover import handover_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["handover"], dependencies=[Depends(require_api_key)])


class HandoverRequestModel(BaseModel):
    session_id: str
    source: str = "wechat"
    nickname: str = ""
    reason: str = ""


class AssignModel(BaseModel):
    owner: str = ""


@router.get("/handovers")
async def list_handovers(status: str = Query(""), limit: int = Query(200, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"handovers": filter_by_tenant(handover_manager.list(status=status, limit=limit), tenant_id)}


@router.get("/handovers/stats")
async def handover_stats():
    return handover_manager.stats()


@router.post("/handovers/request")
async def request_handover(req: HandoverRequestModel):
    return handover_manager.request(
        session_id=req.session_id,
        source=req.source,
        nickname=req.nickname,
        reason=req.reason,
    )


@router.post("/handovers/{request_id}/assign", dependencies=[Depends(require_admin)])
async def assign_handover(request_id: int, req: AssignModel):
    return {"handover": handover_manager.assign(request_id, req.owner)}


@router.post("/handovers/{request_id}/complete", dependencies=[Depends(require_admin)])
async def complete_handover(request_id: int):
    return {"handover": handover_manager.complete(request_id)}
