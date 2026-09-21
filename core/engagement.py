"""业务工具集成：预约、优惠券、支付链接"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import Appointment, Coupon, PaymentLink, UserCoupon

logger = logging.getLogger(__name__)

APPOINTMENT_STATUSES = ["pending", "confirmed", "done", "cancelled"]
COUPON_STATUSES = ["active", "disabled"]
USER_COUPON_STATUSES = ["unused", "used", "expired"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _future(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _fill(kwargs: dict, allowed: set) -> dict:
    return {k: v for k, v in kwargs.items() if k in allowed and v is not None}


class EngagementManager:
    def __init__(self):
        init_db()

    # ---------- 预约 ----------
    def create_appointment(self, **fields) -> dict:
        allowed = {"session_id", "customer_id", "lead_id", "order_id", "appointment_type", "title", "start_at", "end_at", "owner", "note"}
        with session_scope() as session:
            obj = Appointment(**{**_fill(fields, allowed), "status": "pending"})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_appointment(self, appointment_id: int, status: str = "", note: str = "") -> dict | None:
        with session_scope() as session:
            obj = session.get(Appointment, appointment_id)
            if not obj:
                return None
            if status and status in APPOINTMENT_STATUSES:
                obj.status = status
            if note:
                obj.note = note
            obj.updated_at = _now()
            return _row_to_dict(obj)

    def list_appointments(self, status: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(Appointment).order_by(Appointment.start_at)
            if status:
                query = query.where(Appointment.status == status)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    # ---------- 优惠券 ----------
    def create_coupon(self, **fields) -> dict:
        allowed = {"name", "coupon_type", "value", "min_amount", "valid_days", "quota"}
        with session_scope() as session:
            obj = Coupon(**{**_fill(fields, allowed), "status": "active"})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_coupon(self, coupon_id: int, **fields) -> dict | None:
        allowed = {"name", "coupon_type", "value", "min_amount", "valid_days", "quota", "status"}
        with session_scope() as session:
            obj = session.get(Coupon, coupon_id)
            if not obj:
                return None
            for k, v in _fill(fields, allowed).items():
                setattr(obj, k, v)
            obj.updated_at = _now()
            return _row_to_dict(obj)

    def list_coupons(self, status: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(Coupon).order_by(Coupon.id.desc())
            if status:
                query = query.where(Coupon.status == status)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    def grant_coupon(self, coupon_id: int, session_id: str = "", customer_id: int = None, lead_id: int = None) -> dict | None:
        with session_scope() as session:
            coupon = session.get(Coupon, coupon_id)
            if not coupon or coupon.status != "active":
                return None
            obj = UserCoupon(
                coupon_id=coupon_id,
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                status="unused",
                expires_at=_future(int(coupon.valid_days or 7)),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_user_coupons(self, session_id: str = "", status: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(UserCoupon).order_by(UserCoupon.id.desc())
            if session_id:
                query = query.where(UserCoupon.session_id == session_id)
            if status:
                query = query.where(UserCoupon.status == status)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    # ---------- 支付链接 ----------
    def create_payment_link(self, order_id: int, title: str = "", amount: float = 0, link: str = "", qr_text: str = "", session_id: str = "", customer_id: int = None, lead_id: int = None, valid_days: int = 7) -> dict | None:
        with session_scope() as session:
            from core.models import Order
            order = session.get(Order, order_id)
            if not order:
                return None
            obj = PaymentLink(
                order_id=order_id,
                session_id=session_id or order.session_id or "",
                customer_id=customer_id or order.customer_id,
                lead_id=lead_id or order.lead_id,
                title=title or order.product_name or "课程订单",
                amount=float(amount or order.amount or 0),
                pay_method="wechat",
                link=link or "",
                qr_text=qr_text or "",
                status="pending",
                expires_at=_future(int(valid_days or 7)),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_payment_links(self, status: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(PaymentLink).order_by(PaymentLink.id.desc())
            if status:
                query = query.where(PaymentLink.status == status)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    def update_payment_link(self, link_id: int, status: str = "", link: str = "", qr_text: str = "") -> dict | None:
        with session_scope() as session:
            obj = session.get(PaymentLink, link_id)
            if not obj:
                return None
            if status:
                obj.status = status
            if link:
                obj.link = link
            if qr_text:
                obj.qr_text = qr_text
            return _row_to_dict(obj)

    def stats(self) -> dict:
        appointments = self.list_appointments(limit=100000)
        coupons = self.list_coupons(limit=100000)
        user_coupons = self.list_user_coupons(limit=100000)
        payment_links = self.list_payment_links(limit=100000)
        return {
            "appointments": len(appointments),
            "appointments_pending": sum(1 for a in appointments if a.get("status") == "pending"),
            "coupons": len(coupons),
            "coupons_active": sum(1 for c in coupons if c.get("status") == "active"),
            "coupons_issued": len(user_coupons),
            "coupons_used": sum(1 for c in user_coupons if c.get("status") == "used"),
            "payment_links": len(payment_links),
            "payment_links_paid": sum(1 for p in payment_links if p.get("status") == "paid"),
        }



    def delete_appointment(self, appointment_id: int) -> bool:
        with session_scope() as session:
            obj = session.get(Appointment, appointment_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_coupon(self, coupon_id: int) -> bool:
        with session_scope() as session:
            obj = session.get(Coupon, coupon_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_payment_link(self, link_id: int) -> bool:
        with session_scope() as session:
            obj = session.get(PaymentLink, link_id)
            if not obj:
                return False
            session.delete(obj)
            return True


engagement_manager = EngagementManager()
