"""自动跟进接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.followup import followup_engine
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["followups"], dependencies=[Depends(require_api_key)])


class PlanRequest(BaseModel):
    session_id: str = ""
    lead_id: int = None
    customer_id: int = None


@router.get("/followups/tasks")
async def list_tasks(status: str = Query(""), limit: int = Query(200, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"tasks": filter_by_tenant(followup_engine.list_tasks(status=status, limit=limit), tenant_id)}


@router.get("/followups/stats")
async def followup_stats():
    return followup_engine.stats()


@router.post("/followups/plan")
async def create_plan(req: PlanRequest):
    created = 0
    if req.customer_id:
        from core.sales_crm import crm
        customer = crm.get(req.customer_id)
        if customer:
            created = followup_engine.plan_for_customer(customer)
    elif req.lead_id:
        from core.lead import lead_manager
        lead = lead_manager.get(req.lead_id)
        if lead:
            created = followup_engine.plan_for_lead(lead)
    elif req.session_id:
        from core.sales_crm import crm
        customer = crm.get_by_session(req.session_id)
        if not customer and str(req.session_id).isdigit():
            try:
                customer = crm.get(int(req.session_id))
            except Exception:
                customer = None
        if customer:
            created = followup_engine.plan_for_customer(customer)
        else:
            from core.lead import lead_manager
            lead = lead_manager.get_by_session_id(req.session_id)
            if not lead and str(req.session_id).isdigit():
                try:
                    lead = lead_manager.get(int(req.session_id))
                except Exception:
                    lead = None
            if lead:
                created = followup_engine.plan_for_lead(lead)
    note = "" if created else "未找到客户/线索，或该客户已有进行中的跟进计划"
    tasks = []
    if created == 0 and req.session_id:
        try:
            tasks = [
                t for t in followup_engine.list_tasks(limit=2000)
                if str(t.get("customer_id") or "") == req.session_id
                or str(t.get("lead_id") or "") == req.session_id
                or t.get("session_id") == req.session_id
            ]
        except Exception:
            tasks = []
    return {"created": created, "note": note, "tasks": tasks}


@router.post("/followups/dispatch", dependencies=[Depends(require_admin)])
async def dispatch_due():
    return {"sent": followup_engine.dispatch_due()}
