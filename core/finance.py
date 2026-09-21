"""回款与 L2C：发货、开票、回款计划、应收核销"""
from __future__ import annotations
import logging
from datetime import datetime

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import Invoice, Payment, PaymentPlan, Receivable, Shipment

logger = logging.getLogger(__name__)

SHIPMENT_STATUSES = ["pending", "shipped", "delivered", "cancelled"]
INVOICE_STATUSES = ["unpaid", "issued", "paid"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _make_no(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{datetime.now().microsecond % 10000:04d}"


class FinanceManager:
    def __init__(self):
        init_db()

    # ---------- 发货 ----------
    def create_shipment(
        self,
        order_id: int,
        tracking_no: str = "",
        carrier: str = "",
        address: str = "",
    ) -> dict | None:
        with session_scope() as session:
            from core.models import Order
            order = session.get(Order, order_id)
            if not order:
                return None
            obj = Shipment(
                order_id=order_id,
                tracking_no=tracking_no or "",
                carrier=carrier or "",
                status="pending",
                address=address or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_shipment(self, shipment_id: int, status: str = "", tracking_no: str = "", carrier: str = "") -> dict | None:
        with session_scope() as session:
            obj = session.get(Shipment, shipment_id)
            if not obj:
                return None
            if status and status in SHIPMENT_STATUSES:
                obj.status = status
                if status == "shipped":
                    obj.ship_at = _now()
                elif status == "delivered":
                    obj.delivered_at = _now()
            if tracking_no:
                obj.tracking_no = tracking_no
            if carrier:
                obj.carrier = carrier
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def list_shipments(self, status: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(Shipment).order_by(Shipment.id.desc())
            if status:
                query = query.where(Shipment.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 开票 ----------
    def create_invoice(
        self,
        order_id: int,
        amount: float = 0,
        title: str = "",
        tax_no: str = "",
    ) -> dict | None:
        with session_scope() as session:
            from core.models import Order
            order = session.get(Order, order_id)
            if not order:
                return None
            obj = Invoice(
                invoice_no=_make_no("INV"),
                order_id=order_id,
                amount=float(amount or order.amount or 0),
                title=title or "",
                tax_no=tax_no or "",
                status="unpaid",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def change_invoice_status(self, invoice_id: int, status: str) -> dict | None:
        if status not in INVOICE_STATUSES:
            return None
        with session_scope() as session:
            obj = session.get(Invoice, invoice_id)
            if not obj:
                return None
            obj.status = status
            if status == "issued":
                obj.issued_at = _now()
            elif status == "paid":
                obj.paid_at = _now()
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def list_invoices(self, status: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(Invoice).order_by(Invoice.id.desc())
            if status:
                query = query.where(Invoice.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 回款计划 ----------
    def create_payment_plans(self, order_id: int, amounts: list[float], due_dates: list[str]) -> dict | None:
        with session_scope() as session:
            from core.models import Order
            order = session.get(Order, order_id)
            if not order:
                return None
            total = sum(float(a or 0) for a in amounts)
            if total <= 0:
                total = float(order.amount or 0)
                step = total / max(len(due_dates), 1)
                amounts = [step] * len(due_dates)
            plans = []
            for seq, (amount, due_at) in enumerate(zip(amounts, due_dates), start=1):
                plan = PaymentPlan(
                    order_id=order_id,
                    plan_no=f"{order.order_no}-{seq:02d}",
                    seq=seq,
                    amount=round(float(amount), 2),
                    due_at=due_at or "",
                    status="pending",
                )
                session.add(plan)
                session.flush()
                session.add(Receivable(
                    order_id=order_id,
                    plan_id=plan.id,
                    amount=round(float(amount), 2),
                    received_amount=0,
                    status="unpaid",
                    due_at=due_at or "",
                ))
                plans.append(_row_to_dict(plan))
            return {"order_id": order_id, "plans": plans}

    def list_payment_plans(self, order_id: int = 0, status: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(PaymentPlan).order_by(PaymentPlan.order_id, PaymentPlan.seq)
            if order_id:
                query = query.where(PaymentPlan.order_id == order_id)
            if status:
                query = query.where(PaymentPlan.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 应收与核销 ----------
    def list_receivables(self, status: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(Receivable).order_by(Receivable.due_at)
            if status:
                query = query.where(Receivable.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def record_receipt(
        self,
        receivable_id: int,
        amount: float,
        method: str = "",
        transaction_id: str = "",
    ) -> dict | None:
        amount = float(amount or 0)
        with session_scope() as session:
            obj = session.get(Receivable, receivable_id)
            if not obj or amount <= 0:
                return None
            received = float(obj.received_amount or 0) + amount
            obj.received_amount = round(min(received, float(obj.amount or 0)), 2)
            obj.last_received_at = _now()
            obj.status = "paid" if obj.received_amount >= float(obj.amount or 0) else "partial"
            obj.updated_at = _now()
            session.add(Payment(
                order_id=obj.order_id,
                amount=amount,
                method=method or "transfer",
                transaction_id=transaction_id or "",
                status="paid",
                paid_at=_now(),
            ))
            session.flush()
            result = _row_to_dict(obj)
            if obj.plan_id:
                plan = session.get(PaymentPlan, obj.plan_id)
                if plan and result.get("status") == "paid":
                    plan.status = "paid"
                    plan.paid_at = _now()
                    plan.updated_at = _now()
                elif plan and result.get("status") == "partial":
                    plan.status = "partial"
                    plan.updated_at = _now()
            return result

    def refresh_overdue(self) -> dict:
        now = _now()
        with session_scope() as session:
            plans = session.execute(
                select(PaymentPlan).where(
                    PaymentPlan.status == "pending",
                    PaymentPlan.due_at != "",
                    PaymentPlan.due_at < now,
                )
            ).scalars().all()
            for plan in plans:
                plan.status = "overdue"
                plan.updated_at = _now()
            receivables = session.execute(
                select(Receivable).where(
                    Receivable.status.in_(["unpaid", "partial"]),
                    Receivable.due_at != "",
                    Receivable.due_at < now,
                )
            ).scalars().all()
            for obj in receivables:
                obj.status = "overdue"
                obj.updated_at = _now()
            return {"plans": len(plans), "receivables": len(receivables)}

    def stats(self) -> dict:
        receivables = self.list_receivables(limit=100000)
        invoices = self.list_invoices(limit=100000)
        shipments = self.list_shipments(limit=100000)
        total = sum(float(r.get("amount") or 0) for r in receivables)
        received = sum(float(r.get("received_amount") or 0) for r in receivables)
        overdue = sum(float(r.get("amount") or 0) - float(r.get("received_amount") or 0)
                      for r in receivables if r.get("status") == "overdue")
        return {
            "receivables_total": round(total, 2),
            "received": round(received, 2),
            "outstanding": round(total - received, 2),
            "overdue": round(max(overdue, 0), 2),
            "receivable_count": len(receivables),
            "overdue_count": sum(1 for r in receivables if r.get("status") == "overdue"),
            "invoices": len(invoices),
            "invoices_paid": sum(1 for i in invoices if i.get("status") == "paid"),
            "shipments": len(shipments),
            "shipments_pending": sum(1 for s in shipments if s.get("status") == "pending"),
        }


finance_manager = FinanceManager()
