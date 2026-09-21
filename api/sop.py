"""可配置销售 SOP 接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.sop import sop_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["sop"], dependencies=[Depends(require_api_key)])


class TemplateCreate(BaseModel):
    name: str
    stage: str = ""
    steps: list[dict] = []


class TemplateUpdate(BaseModel):
    name: str = ""
    stage: str = ""
    steps: list[dict] = None
    active: bool = None


class ExecutionStart(BaseModel):
    template_id: int
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None


@router.get("/sop/templates")
async def list_templates(stage: str = Query(""), active_only: bool = Query(False), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"templates": filter_by_tenant(sop_manager.list_templates(stage=stage, active_only=active_only), tenant_id)}


@router.post("/sop/templates", dependencies=[Depends(require_admin)])
async def create_template(req: TemplateCreate):
    return {"template": sop_manager.create_template(req.name, req.stage, req.steps)}


@router.patch("/sop/templates/{template_id}", dependencies=[Depends(require_admin)])
async def update_template(template_id: int, req: TemplateUpdate):
    return {"template": sop_manager.update_template(
        template_id, req.name, req.stage, req.steps,
        req.active if req.active is not None else None,
    )}


@router.get("/sop/executions")
async def list_executions(status: str = Query(""), stage: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"executions": filter_by_tenant(sop_manager.list_executions(status=status, stage=stage, limit=limit), tenant_id)}


@router.post("/sop/executions", dependencies=[Depends(require_admin)])
async def start_execution(req: ExecutionStart):
    return sop_manager.start_execution(
        req.template_id,
        session_id=req.session_id,
        customer_id=req.customer_id,
        lead_id=req.lead_id,
    )


@router.post("/sop/executions/{execution_id}/complete", dependencies=[Depends(require_admin)])
async def complete_execution(execution_id: int):
    return {"execution": sop_manager.complete_step(execution_id)}


@router.post("/sop/executions/{execution_id}/skip", dependencies=[Depends(require_admin)])
async def skip_execution(execution_id: int):
    return {"execution": sop_manager.skip_step(execution_id)}


@router.post("/sop/refresh-overdue", dependencies=[Depends(require_admin)])
async def refresh_overdue():
    return sop_manager.refresh_overdue()


@router.get("/sop/stats")
async def sop_stats():
    return sop_manager.stats()
