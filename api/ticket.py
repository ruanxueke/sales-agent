"""工单、SLA 与回访接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.ticket import ticket_manager
from core.security import require_admin, require_api_key
import logging
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1", tags=["tickets"], dependencies=[Depends(require_api_key)])


class TicketCreate(BaseModel):
    title: str
    description: str = ""
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None
    priority: str = "medium"
    category: str = ""
    owner: str = ""


class TicketUpdate(BaseModel):
    title: str = ""
    description: str = ""
    priority: str = ""
    category: str = ""
    owner: str = ""
    status: str = ""
    actor: str = ""


class EventCreate(BaseModel):
    action: str = "update"
    content: str = ""
    actor: str = ""


class VisitCreate(BaseModel):
    content: str
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None
    order_id: int = None
    visit_type: str = "followup"
    next_visit_at: str = ""
    owner: str = ""


@router.get("/tickets")
async def list_tickets(status: str = Query(""), priority: str = Query(""), owner: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"tickets": filter_by_tenant(ticket_manager.list_tickets(status=status, priority=priority, owner=owner, limit=limit), tenant_id)}


@router.post("/tickets", dependencies=[Depends(require_admin)])
async def create_ticket(req: TicketCreate):
    ticket = ticket_manager.create_ticket(**req.model_dump())
    try:
        from datetime import datetime, timedelta
        from pathlib import Path
        from core.enterprise import enterprise
        hours = enterprise.sla_resolve_hours(req.priority or "medium")
        due = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
        from config.settings import settings
        conn = sqlite3.connect(str(Path(settings.DATA_DIR) / "customers.db"))
        conn.execute("UPDATE tickets SET sla_due_at = ? WHERE id = ?", (due, ticket["id"]))
        conn.commit()
        conn.close()
        ticket["sla_due_at"] = due
    except Exception as e:
        logger.debug("create_ticket 异常已忽略: %s", e)
    return {"ticket": ticket}


@router.patch("/tickets/{ticket_id}", dependencies=[Depends(require_admin)])
async def update_ticket(ticket_id: int, req: TicketUpdate):
    return {"ticket": ticket_manager.update_ticket(**{**{"ticket_id": ticket_id}, **req.model_dump()})}


@router.get("/tickets/{ticket_id}/events")
async def ticket_events(ticket_id: int, limit: int = Query(100, le=500)):
    return {"events": ticket_manager.ticket_events(ticket_id, limit=limit)}


@router.post("/tickets/{ticket_id}/events", dependencies=[Depends(require_admin)])
async def add_ticket_event(ticket_id: int, req: EventCreate):
    return {"event": ticket_manager.add_event(ticket_id, req.action, req.content, req.actor)}


@router.get("/visits")
async def list_visits(session_id: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"visits": filter_by_tenant(ticket_manager.list_visits(session_id=session_id, limit=limit), tenant_id)}


@router.post("/visits", dependencies=[Depends(require_admin)])
async def create_visit(req: VisitCreate):
    return {"visit": ticket_manager.create_visit(**req.model_dump())}


@router.post("/tickets/refresh-overdue", dependencies=[Depends(require_admin)])
async def refresh_overdue():
    return ticket_manager.refresh_overdue()


@router.get("/tickets/stats")
async def ticket_stats():
    return ticket_manager.stats()
