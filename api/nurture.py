"""个性化培育接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.nurture import nurture_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["nurture"], dependencies=[Depends(require_api_key)])


class CampaignModel(BaseModel):
    name: str
    trigger_type: str = "stage"
    trigger_value: str = ""
    description: str = ""


class CampaignUpdate(BaseModel):
    name: str = ""
    status: str = ""
    trigger_type: str = ""
    trigger_value: str = ""
    description: str = ""


class RuleModel(BaseModel):
    campaign_id: int
    sequence: int = 1
    content: str
    condition_type: str = "always"
    condition_value: str = ""
    delay_hours: int = 0


@router.get("/nurture/campaigns")
async def list_campaigns(status: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"campaigns": filter_by_tenant(nurture_manager.list_campaigns(status=status, limit=limit), tenant_id)}


@router.post("/nurture/campaigns", dependencies=[Depends(require_admin)])
async def create_campaign(req: CampaignModel):
    return {"campaign": nurture_manager.create_campaign(**req.model_dump())}


@router.patch("/nurture/campaigns/{campaign_id}", dependencies=[Depends(require_admin)])
async def update_campaign(campaign_id: int, req: CampaignUpdate):
    data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    return {"campaign": nurture_manager.update_campaign(campaign_id, **data)}


@router.get("/nurture/rules")
async def list_rules(campaign_id: int = Query(0), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"rules": filter_by_tenant(nurture_manager.list_rules(campaign_id=campaign_id, limit=limit), tenant_id)}


@router.post("/nurture/rules", dependencies=[Depends(require_admin)])
async def add_rule(req: RuleModel):
    return {"rule": nurture_manager.add_rule(**req.model_dump())}


@router.get("/nurture/events")
async def list_events(status: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"events": filter_by_tenant(nurture_manager.list_events(status=status, limit=limit), tenant_id)}


@router.post("/nurture/dispatch", dependencies=[Depends(require_admin)])
async def dispatch_due():
    return nurture_manager.dispatch_due()


@router.get("/nurture/stats")
async def nurture_stats():
    return nurture_manager.stats()
