"""SLA 策略与客户分级接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.enterprise import enterprise
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["service"], dependencies=[Depends(require_api_key)])


class SlaCreate(BaseModel):
    priority: str
    name: str
    respond_hours: float = 2
    resolve_hours: float = 24


class TierCreate(BaseModel):
    tier: str
    name: str
    min_amount: float = 0
    priority_boost: int = 0


@router.get("/sla/policies")
async def list_sla():
    return {"items": enterprise.list_sla_policies()}


@router.post("/sla/policies", dependencies=[Depends(require_admin)])
async def create_sla(req: SlaCreate):
    return {"item": enterprise.create_sla_policy(req.priority, req.name, req.respond_hours, req.resolve_hours)}


@router.get("/customer-tiers")
async def list_tiers():
    return {"items": enterprise.list_customer_tiers()}


@router.post("/customer-tiers", dependencies=[Depends(require_admin)])
async def create_tier(req: TierCreate):
    return {"item": enterprise.create_customer_tier(req.tier, req.name, req.min_amount, req.priority_boost)}
