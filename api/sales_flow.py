"""销售流程企业级 API：可配置工作流、预测管道、智能派单"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from core.sales_flow import sales_flow
from core.security import current_tenant, require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["sales-flow"], dependencies=[Depends(require_api_key)])


class WorkflowCreate(BaseModel):
    name: str
    trigger: str = "manual"
    nodes: list[dict] = []
    enabled: bool = True


class WorkflowUpdate(BaseModel):
    name: str = ""
    trigger: str = ""
    nodes: list[dict] = None
    enabled: bool = None


class TriggerEventModel(BaseModel):
    event: str
    context: dict = {}


class DispatchRuleCreate(BaseModel):
    name: str
    strategy: str = "round_robin"
    params: dict = {}
    enabled: bool = True


class DispatchRequest(BaseModel):
    lead_id: int
    strategy: str = ""


class ReassignRequest(BaseModel):
    lead_id: int
    owner: str


def _tenant(request: Request):
    return current_tenant(request)


# ===== 工作流 =====

@router.get("/sales-flow/overview")
async def sales_flow_overview(request: Request = None):
    tenant_id = current_tenant(request)
    return {
        "workflow": sales_flow.workflow_stats(tenant_id),
        "dispatch": sales_flow.dispatch_stats(tenant_id),
        "prediction": sales_flow.predictions(tenant_id, limit=10),
    }


@router.get("/sales-flow/workflows")
async def list_workflows(request: Request = None):
    return {"items": sales_flow.list_workflows(current_tenant(request))}


@router.post("/sales-flow/workflows", dependencies=[Depends(require_admin)])
async def create_workflow(req: WorkflowCreate, request: Request = None):
    try:
        workflow = sales_flow.create_workflow(
            current_tenant(request), req.name, req.trigger, req.nodes, req.enabled,
        )
        return {"ok": True, "workflow": workflow}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.patch("/sales-flow/workflows/{workflow_id}", dependencies=[Depends(require_admin)])
async def update_workflow(workflow_id: int, req: WorkflowUpdate, request: Request = None):
    workflow = sales_flow.update_workflow(
        workflow_id,
        current_tenant(request),
        name=req.name,
        trigger=req.trigger,
        nodes=req.nodes,
        enabled=req.enabled,
    )
    return {"ok": bool(workflow), "workflow": workflow}


@router.delete("/sales-flow/workflows/{workflow_id}", dependencies=[Depends(require_admin)])
async def delete_workflow(workflow_id: int, request: Request = None):
    return {"ok": sales_flow.delete_workflow(workflow_id, current_tenant(request))}


@router.post("/sales-flow/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: int, payload: dict = None, request: Request = None):
    return sales_flow.run_workflow(workflow_id, payload or {}, current_tenant(request))


@router.post("/sales-flow/trigger")
async def trigger_event(req: TriggerEventModel, request: Request = None):
    results = sales_flow.trigger_event(req.event, req.context, current_tenant(request))
    return {"ok": True, "matched": len(results), "results": results}


@router.get("/sales-flow/executions")
async def list_executions(limit: int = Query(100, le=500), request: Request = None):
    return {"items": sales_flow.list_executions(current_tenant(request), limit)}


# ===== 预测管道 =====

@router.get("/sales-flow/predictions")
async def predictions(limit: int = Query(50, le=200), request: Request = None):
    return sales_flow.predictions(current_tenant(request), limit)


# ===== 智能派单 =====

@router.get("/sales-flow/dispatch/rules")
async def list_dispatch_rules(request: Request = None):
    return {"items": sales_flow.list_dispatch_rules(current_tenant(request))}


@router.post("/sales-flow/dispatch/rules", dependencies=[Depends(require_admin)])
async def create_dispatch_rule(req: DispatchRuleCreate, request: Request = None):
    return {"rule": sales_flow.create_dispatch_rule(
        current_tenant(request), req.name, req.strategy, req.params, req.enabled,
    )}


@router.delete("/sales-flow/dispatch/rules/{rule_id}", dependencies=[Depends(require_admin)])
async def delete_dispatch_rule(rule_id: int, request: Request = None):
    return {"ok": sales_flow.delete_dispatch_rule(rule_id, current_tenant(request))}


@router.get("/sales-flow/dispatch/candidates")
async def dispatch_candidates(request: Request = None):
    return {"items": sales_flow.dispatch_candidates(current_tenant(request))}


@router.get("/sales-flow/dispatch/stats")
async def dispatch_stats(request: Request = None):
    return sales_flow.dispatch_stats(current_tenant(request))


@router.post("/sales-flow/dispatch")
async def dispatch_lead(req: DispatchRequest, request: Request = None):
    return sales_flow.dispatch_lead(req.lead_id, current_tenant(request), req.strategy)


@router.post("/sales-flow/reassign")
async def reassign_lead(req: ReassignRequest, request: Request = None):
    from core.lead import lead_manager
    lead = lead_manager.assign(req.lead_id, req.owner)
    if not lead:
        return {"ok": False, "error": "线索不存在"}
    return {"ok": True, "lead": lead}
