"""服务工单 / SLA / 回访"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import Ticket, TicketEvent, Visit

logger = logging.getLogger(__name__)

PRIORITY_SLA_HOURS = {"urgent": 4, "high": 24, "medium": 48, "low": 72}
TICKET_STATUSES = ["open", "processing", "resolved", "closed"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _datetime_plus_hours(hours: int) -> str:
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _make_no() -> str:
    return f"TK{datetime.now().strftime('%Y%m%d%H%M%S')}{datetime.now().microsecond % 10000:04d}"


class TicketManager:
    def __init__(self):
        init_db()

    def create_ticket(
        self,
        title: str,
        description: str = "",
        session_id: str = "",
        customer_id: int = None,
        lead_id: int = None,
        priority: str = "medium",
        category: str = "",
        owner: str = "",
    ) -> dict:
        priority = priority if priority in PRIORITY_SLA_HOURS else "medium"
        sla_hours = PRIORITY_SLA_HOURS[priority]
        with session_scope() as session:
            obj = Ticket(
                ticket_no=_make_no(),
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                title=title or "未命名工单",
                description=description or "",
                priority=priority,
                category=category or "",
                status="open",
                owner=owner or "",
                sla_due_at=_datetime_plus_hours(sla_hours),
            )
            session.add(obj)
            session.flush()
            self._event(session, obj.id, "created", "工单创建", owner or "system")
            return _row_to_dict(obj)

    def update_ticket(
        self,
        ticket_id: int,
        title: str = "",
        description: str = "",
        priority: str = "",
        category: str = "",
        owner: str = "",
        status: str = "",
        actor: str = "",
    ) -> dict | None:
        with session_scope() as session:
            obj = session.get(Ticket, ticket_id)
            if not obj:
                return None
            if title:
                obj.title = title
            if description:
                obj.description = description
            if priority and priority in PRIORITY_SLA_HOURS:
                obj.priority = priority
                obj.sla_due_at = _datetime_plus_hours(PRIORITY_SLA_HOURS[priority])
            if category:
                obj.category = category
            if owner:
                obj.owner = owner
            if status and status in TICKET_STATUSES:
                obj.status = status
                if status == "resolved":
                    obj.resolved_at = _now()
                self._event(session, ticket_id, "status", f"状态变更为 {status}", actor or "")
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def add_event(self, ticket_id: int, action: str, content: str, actor: str = "") -> dict | None:
        with session_scope() as session:
            obj = session.get(Ticket, ticket_id)
            if not obj:
                return None
            event = self._event(session, ticket_id, action or "update", content or "", actor or "")
            return event

    def list_tickets(self, status: str = "", priority: str = "", owner: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(Ticket).order_by(Ticket.id.desc())
            if status:
                query = query.where(Ticket.status == status)
            if priority:
                query = query.where(Ticket.priority == priority)
            if owner:
                query = query.where(Ticket.owner == owner)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def list_for_session(self, session_id: str, limit: int = 100) -> list[dict]:
        if not session_id:
            return []
        with session_scope() as session:
            rows = session.execute(
                select(Ticket)
                .where(Ticket.session_id == session_id)
                .order_by(Ticket.id.desc())
                .limit(limit)
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def ticket_events(self, ticket_id: int, limit: int = 100) -> list[dict]:
        with session_scope() as session:
            rows = session.execute(
                select(TicketEvent)
                .where(TicketEvent.ticket_id == ticket_id)
                .order_by(TicketEvent.id.desc())
                .limit(limit)
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 回访 ----------
    def create_visit(
        self,
        content: str,
        session_id: str = "",
        customer_id: int = None,
        lead_id: int = None,
        order_id: int = None,
        visit_type: str = "followup",
        next_visit_at: str = "",
        owner: str = "",
    ) -> dict:
        with session_scope() as session:
            obj = Visit(
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                order_id=order_id,
                visit_type=visit_type or "followup",
                content=content or "",
                next_visit_at=next_visit_at or "",
                owner=owner or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_visits(self, session_id: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(Visit).order_by(Visit.id.desc())
            if session_id:
                query = query.where(Visit.session_id == session_id)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def refresh_overdue(self) -> dict:
        now = _now()
        with session_scope() as session:
            rows = session.execute(
                select(Ticket).where(
                    Ticket.status.in_(["open", "processing"]),
                    Ticket.sla_due_at != "",
                    Ticket.sla_due_at < now,
                )
            ).scalars().all()
            for obj in rows:
                existing = session.execute(
                    select(TicketEvent).where(
                        TicketEvent.ticket_id == obj.id,
                        TicketEvent.action == "sla_overdue",
                    )
                ).scalars().first()
                if existing:
                    continue
                self._event(session, obj.id, "sla_overdue", "超过SLA时限", "system")
            return {"overdue": len(rows)}

    def stats(self) -> dict:
        tickets = self.list_tickets(limit=100000)
        visits = self.list_visits(limit=100000)
        by_status = {}
        by_priority = {}
        overdue = 0
        resolve_hours = []
        for t in tickets:
            status = t.get("status") or "open"
            by_status[status] = by_status.get(status, 0) + 1
            priority = t.get("priority") or "medium"
            by_priority[priority] = by_priority.get(priority, 0) + 1
            sla = t.get("sla_due_at") or ""
            if status in ("open", "processing") and sla and sla < _now():
                overdue += 1
            if status in ("resolved", "closed") and t.get("resolved_at"):
                try:
                    created = datetime.strptime(t.get("created_at") or "", "%Y-%m-%d %H:%M:%S")
                    resolved = datetime.strptime(t["resolved_at"], "%Y-%m-%d %H:%M:%S")
                    resolve_hours.append((resolved - created).total_seconds() / 3600)
                except ValueError as e:
                    logger.debug("TicketManager.stats 异常已忽略: %s", e)
        return {
            "total": len(tickets),
            "open": by_status.get("open", 0),
            "processing": by_status.get("processing", 0),
            "resolved": by_status.get("resolved", 0),
            "overdue": overdue,
            "avg_resolve_hours": round(sum(resolve_hours) / len(resolve_hours), 1) if resolve_hours else 0,
            "by_status": by_status,
            "by_priority": by_priority,
            "visits": len(visits),
        }

    @staticmethod
    def _event(session, ticket_id: int, action: str, content: str, actor: str) -> dict:
        obj = TicketEvent(
            ticket_id=ticket_id,
            action=action or "",
            content=content or "",
            actor=actor or "",
        )
        session.add(obj)
        session.flush()
        return _row_to_dict(obj)


ticket_manager = TicketManager()
