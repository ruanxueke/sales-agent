"""质检与陪练接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.quality import quality_checker
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["quality"], dependencies=[Depends(require_api_key)])


class CheckRequest(BaseModel):
    customer_id: int = None
    session_id: str = ""


class CoachRequest(BaseModel):
    stage: str = "异议处理"
    topic: str = ""


@router.post("/quality/check")
async def check_quality(req: CheckRequest):
    report = quality_checker.check_customer(
        customer_id=req.customer_id,
        session_id=req.session_id,
    )
    return {"report": report}


@router.get("/quality/reports")
async def list_reports(limit: int = Query(200, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"reports": filter_by_tenant(quality_checker.list_reports(limit=limit), tenant_id)}


@router.get("/quality/stats")
async def quality_stats():
    return quality_checker.stats()


@router.post("/quality/coach")
async def coach(req: CoachRequest):
    return {"message": quality_checker.coach(stage=req.stage, topic=req.topic)}


@router.post("/quality/scan", dependencies=[Depends(require_admin)])
async def scan_active():
    return {"checked": quality_checker.scan_active_customers()}
