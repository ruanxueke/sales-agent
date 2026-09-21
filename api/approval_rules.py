"""审批规则接口：报价/合同/折扣自动送审"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.enterprise import enterprise
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["approval"], dependencies=[Depends(require_api_key)])


class RuleCreate(BaseModel):
    biz_type: str
    name: str
    condition_key: str
    operator: str = ">"
    threshold: float = 0
    approver: str = "主管"
    level: int = 1


@router.get("/approval/rules")
async def list_rules():
    return {"items": enterprise.list_approval_rules()}


@router.post("/approval/rules", dependencies=[Depends(require_admin)])
async def create_rule(req: RuleCreate):
    return {"item": enterprise.create_approval_rule(
        req.biz_type, req.name, req.condition_key, req.operator,
        req.threshold, req.approver, req.level,
    )}


@router.delete("/approval/rules/{rule_id}", dependencies=[Depends(require_admin)])
async def delete_rule(rule_id: int):
    return {"deleted": enterprise.delete_approval_rule(rule_id)}
