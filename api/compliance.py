"""合规与人工层接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from core.compliance import compliance_manager
from core.security import current_tenant, require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["compliance"], dependencies=[Depends(require_api_key)])


class RuleModel(BaseModel):
    rule_type: str = "handover"
    trigger_words: str
    action: str = "handover"
    priority: int = 0
    description: str = ""


class UpdateModel(BaseModel):
    fields: dict = {}


@router.get("/compliance/rules")
async def list_rules(
    request: Request,
    rule_type: str = Query(""),
    enabled_only: bool = Query(False),
):
    return {
        "rules": compliance_manager.list_rules(
            rule_type=rule_type,
            enabled_only=enabled_only,
            tenant_id=current_tenant(request),
        )
    }


@router.post("/compliance/rules", dependencies=[Depends(require_admin)])
async def create_rule(req: RuleModel, request: Request):
    return {
        "rule": compliance_manager.create_rule(
            req.rule_type,
            req.trigger_words,
            req.action,
            req.priority,
            req.description,
            tenant_id=current_tenant(request),
        )
    }


@router.patch("/compliance/rules/{rule_id}", dependencies=[Depends(require_admin)])
async def update_rule(rule_id: int, req: UpdateModel, request: Request):
    return {
        "rule": compliance_manager.update_rule(
            rule_id,
            tenant_id=current_tenant(request),
            **req.fields,
        )
    }

@router.delete("/compliance/rules/{rule_id}", dependencies=[Depends(require_admin)])
async def delete_rule(rule_id: int, request: Request):
    return {
        "deleted": compliance_manager.delete_rule(
            rule_id,
            tenant_id=current_tenant(request),
        )
    }


@router.get("/compliance/stats")
async def compliance_stats(request: Request):
    return compliance_manager.stats(tenant_id=current_tenant(request))
