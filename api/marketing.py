"""营销活动、广告 ROI 与复购计划接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.marketing import marketing_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["marketing"], dependencies=[Depends(require_api_key)])


class CampaignCreate(BaseModel):
    name: str
    channel: str = "official"
    budget: float = 0
    cost: float = 0
    start_at: str = ""
    end_at: str = ""
    target: str = ""
    description: str = ""


class CampaignUpdate(BaseModel):
    name: str = ""
    channel: str = ""
    status: str = ""
    budget: float = None
    cost: float = None
    start_at: str = ""
    end_at: str = ""
    target: str = ""
    description: str = ""


class AdMetricModel(BaseModel):
    campaign_id: int
    metric_date: str
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    cost: float = 0
    revenue: float = 0


class RepurchaseCreate(BaseModel):
    product_name: str
    plan_date: str = ""
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None
    order_id: int = None
    note: str = ""


class RepurchaseUpdate(BaseModel):
    status: str = ""
    plan_date: str = ""
    note: str = ""


@router.get("/campaigns")
async def list_campaigns(status: str = Query(""), channel: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"campaigns": filter_by_tenant(marketing_manager.list_campaigns(status=status, channel=channel, limit=limit), tenant_id)}


@router.post("/campaigns", dependencies=[Depends(require_admin)])
async def create_campaign(req: CampaignCreate):
    return {"campaign": marketing_manager.create_campaign(**req.model_dump())}


@router.patch("/campaigns/{campaign_id}", dependencies=[Depends(require_admin)])
async def update_campaign(campaign_id: int, req: CampaignUpdate):
    data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    return {"campaign": marketing_manager.update_campaign(campaign_id, **data)}


@router.get("/ad-metrics")
async def list_ad_metrics(campaign_id: int = Query(0), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"metrics": filter_by_tenant(marketing_manager.list_ad_metrics(campaign_id=campaign_id, limit=limit), tenant_id)}


@router.post("/ad-metrics", dependencies=[Depends(require_admin)])
async def upsert_ad_metric(req: AdMetricModel):
    return {"metric": marketing_manager.upsert_ad_metric(**req.model_dump())}


@router.get("/repurchases")
async def list_repurchases(status: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"plans": filter_by_tenant(marketing_manager.list_repurchases(status=status, limit=limit), tenant_id)}


@router.post("/repurchases", dependencies=[Depends(require_admin)])
async def create_repurchase(req: RepurchaseCreate):
    return {"plan": marketing_manager.create_repurchase(**req.model_dump())}


@router.patch("/repurchases/{plan_id}", dependencies=[Depends(require_admin)])
async def update_repurchase(plan_id: int, req: RepurchaseUpdate):
    return {"plan": marketing_manager.update_repurchase(plan_id, req.status, req.plan_date, req.note)}


@router.post("/repurchases/dispatch", dependencies=[Depends(require_admin)])
async def dispatch_repurchases():
    return {"dispatched": marketing_manager.dispatch_due_repurchases()}


@router.get("/marketing/stats")
async def marketing_stats():
    return marketing_manager.stats()
