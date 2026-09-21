"""商机管理接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.opportunity import OPPORTUNITY_STAGES, opportunity_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["opportunities"], dependencies=[Depends(require_api_key)])


class OpportunityCreate(BaseModel):
    name: str
    customer_id: int = None
    lead_id: int = None
    session_id: str = ""
    product_name: str = ""
    amount: float = 0
    stage: str = "qualifying"
    win_rate: int = 0
    owner: str = ""
    source: str = ""
    expected_close_at: str = ""
    notes: str = ""


class OpportunityUpdate(BaseModel):
    name: str = ""
    product_name: str = ""
    amount: float = None
    win_rate: int = None
    owner: str = ""
    source: str = ""
    expected_close_at: str = ""
    loss_reason: str = ""
    notes: str = ""


class StageRequest(BaseModel):
    stage: str
    loss_reason: str = ""


@router.get("/opportunities")
async def list_opportunities(
    stage: str = Query(""),
    owner: str = Query(""),
    risk: str = Query(""),
    keyword: str = Query(""),
    limit: int = Query(500, le=2000),
    offset: int = Query(0, ge=0),
    request: Request = None,
):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"opportunities": filter_by_tenant(opportunity_manager.list(
        stage=stage, owner=owner, risk=risk, keyword=keyword, limit=limit, offset=offset,
    ), tenant_id)}


@router.get("/opportunities/stats")
async def opportunity_stats():
    return opportunity_manager.stats()


@router.post("/opportunities", dependencies=[Depends(require_admin)])
async def create_opportunity(req: OpportunityCreate):
    return {"opportunity": opportunity_manager.create(**req.model_dump())}


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: int):
    return {"opportunity": opportunity_manager.get(opportunity_id)}


@router.patch("/opportunities/{opportunity_id}", dependencies=[Depends(require_admin)])
async def update_opportunity(opportunity_id: int, req: OpportunityUpdate):
    data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    return {"opportunity": opportunity_manager.update(opportunity_id, **data)}


@router.post("/opportunities/{opportunity_id}/stage", dependencies=[Depends(require_admin)])
async def mark_opportunity_stage(opportunity_id: int, req: StageRequest):
    if req.stage not in OPPORTUNITY_STAGES:
        return {"opportunity": None, "error": f"未知阶段 {req.stage}"}
    return {"opportunity": opportunity_manager.mark_stage(opportunity_id, req.stage, req.loss_reason)}


@router.post("/opportunities/{opportunity_id}/predict", dependencies=[Depends(require_admin)])
async def predict_win_rate(opportunity_id: int):
    return {"opportunity": opportunity_manager.predict_win_rate(opportunity_id)}


@router.post("/opportunities/refresh-risk", dependencies=[Depends(require_admin)])
async def refresh_risk():
    return opportunity_manager.refresh_risk()
