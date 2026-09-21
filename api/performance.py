"""业绩、佣金、战报、排行榜接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.enterprise import enterprise
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["performance"], dependencies=[Depends(require_api_key)])


class TargetCreate(BaseModel):
    member: str
    period: str
    target_type: str = "amount"
    amount: float = 0


class RuleCreate(BaseModel):
    name: str
    rule_type: str = "percent"
    value: float = 0


@router.get("/team/performance")
async def performance(period: str = Query("")):
    return {"items": enterprise.performance(period)}


@router.get("/team/leaderboard")
async def leaderboard(period: str = Query("")):
    return {"items": enterprise.leaderboard(period)}


@router.get("/team/targets")
async def targets():
    return {"items": enterprise.list_targets()}


@router.post("/team/targets", dependencies=[Depends(require_admin)])
async def create_target(req: TargetCreate):
    return {"item": enterprise.create_target(req.member, req.period, req.target_type, req.amount)}


@router.get("/team/commission-rules")
async def commission_rules():
    return {"items": enterprise.list_commission_rules()}


@router.post("/team/commission-rules", dependencies=[Depends(require_admin)])
async def create_rule(req: RuleCreate):
    return {"item": enterprise.create_commission_rule(req.name, req.rule_type, req.value)}


@router.get("/team/commissions")
async def commissions():
    return {"items": enterprise.list_commissions()}


@router.post("/team/commissions/compute", dependencies=[Depends(require_admin)])
async def compute_commissions():
    return enterprise.compute_commissions()
