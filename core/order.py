"""成交闭环：订单、支付、售后与复购统计"""
from __future__ import annotations
import logging
import time
from datetime import datetime

from sqlalchemy import select

from config.settings import settings
from core.db import init_db, session_scope
from core.models import AfterSale, Order, Payment

logger = logging.getLogger(__name__)

ORDER_STATUSES = ["draft", "paid", "fulfilled", "cancelled", "refunded"]
AFTER_SALE_STATUSES = ["open", "processing", "resolved", "closed"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class OrderManager:
    def create_order(
        self,
        customer_id: int = None,
        lead_id: int = None,
        session_id: str = "",
        customer_name: str = "",
        phone: str = "",
        product_name: str = "",
        amount: float = 0,
        status: str = "draft",
    ) -> dict:
        init_db()
        order_no = f"SO{datetime.now().strftime('%Y%m%d%H%M%S')}{datetime.now().microsecond % 10000:04d}"
        with session_scope() as session:
            obj = Order(
                order_no=order_no,
                customer_id=customer_id,
                lead_id=lead_id,
                session_id=session_id,
                customer_name=customer_name,
                phone=phone,
                product_name=product_name,
                amount=float(amount or 0),
                status=status if status in ORDER_STATUSES else "draft",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def pay_order(
        self,
        order_id: int,
        method: str = "",
        transaction_id: str = "",
    ) -> dict | None:
        init_db()
        with session_scope() as session:
            order = session.get(Order, order_id)
            if not order:
                return None
            already_paid = order.status == "paid"
            order.status = "paid"
            order.pay_method = method or order.pay_method
            order.paid_at = order.paid_at or _now()
            order.updated_at = _now()
            if not already_paid:
                session.add(Payment(
                    order_id=order_id,
                    amount=order.amount,
                    method=method,
                    transaction_id=transaction_id,
                    status="paid",
                    paid_at=_now(),
                ))
            result = _row_to_dict(order)

        if not already_paid:
            self._close_after_payment(result)
        self._deliver_after_payment(result, transaction_id)
        return result

        # 销售流程工作流：订单支付事件
        try:
            from core.sales_flow import sales_flow
            sales_flow.trigger_event("order.paid", {
                "order": result, "order_id": order_id,
                "customer_id": result.get("customer_id"), "lead_id": result.get("lead_id"),
                "session_id": result.get("session_id") or "",
            }, result.get("tenant_id"))
        except Exception as e:
            logger.error("销售流程订单支付事件触发失败: %s", e)
        return result

    def create_after_sale(
        self,
        order_id: int,
        reason: str,
        handler: str = "",
    ) -> dict | None:
        init_db()
        with session_scope() as session:
            order = session.get(Order, order_id)
            if not order:
                return None
            obj = AfterSale(
                order_id=order_id,
                customer_id=order.customer_id,
                session_id=order.session_id,
                reason=reason,
                status="open",
                handler=handler,
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_after_sale(self, after_sale_id: int, status: str, handler: str = "") -> dict | None:
        init_db()
        with session_scope() as session:
            obj = session.get(AfterSale, after_sale_id)
            if not obj:
                return None
            if status in AFTER_SALE_STATUSES:
                obj.status = status
            if handler:
                obj.handler = handler
            obj.updated_at = _now()
            return _row_to_dict(obj)

    def list_orders(self, status: str = "", limit: int = 200) -> list[dict]:
        init_db()
        with session_scope() as session:
            query = select(Order).order_by(Order.id.desc())
            if status:
                query = query.where(Order.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def list_payments(self, limit: int = 200) -> list[dict]:
        init_db()
        with session_scope() as session:
            rows = session.execute(
                select(Payment).order_by(Payment.id.desc()).limit(limit)
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def list_after_sales(self, status: str = "", limit: int = 200) -> list[dict]:
        init_db()
        with session_scope() as session:
            query = select(AfterSale).order_by(AfterSale.id.desc())
            if status:
                query = query.where(AfterSale.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def stats(self) -> dict:
        orders = self.list_orders(limit=100000)
        payments = self.list_payments(limit=100000)
        after_sales = self.list_after_sales(limit=100000)
        total_amount = sum(float(o.get("amount") or 0) for o in orders)
        paid_amount = sum(float(o.get("amount") or 0) for o in orders if o.get("status") == "paid")
        by_status = {}
        for o in orders:
            by_status[o["status"]] = by_status.get(o["status"], 0) + 1
        return {
            "total_orders": len(orders),
            "paid_orders": by_status.get("paid", 0),
            "total_amount": round(total_amount, 2),
            "paid_amount": round(paid_amount, 2),
            "by_status": by_status,
            "total_payments": len(payments),
            "after_sales": len(after_sales),
            "after_sales_open": sum(1 for a in after_sales if a.get("status") in ("open", "processing")),
        }

    @staticmethod
    def _close_after_payment(order: dict) -> None:
        if order.get("customer_id"):
            try:
                from core.sales_crm import crm
                crm.advance_stage(order["customer_id"], "won", trigger="订单支付")
            except Exception as e:
                logger.error(f"订单支付后客户阶段更新失败: {e}")
        if order.get("lead_id"):
            try:
                from core.lead import lead_manager
                lead_manager.mark_status(order["lead_id"], "won")
            except Exception as e:
                logger.error(f"订单支付后线索状态更新失败: {e}")

    @staticmethod
    def _deliver_after_payment(order: dict, transaction_id: str = "") -> None:
        session_id = (order or {}).get("session_id") or ""
        content = getattr(settings, "DELIVERY_MESSAGE", "") or ""
        if not session_id or not content:
            return
        dedup_key = f"pay-deliver-{transaction_id or session_id or order.get('id')}"
        try:
            from core.idempotency import idempotency_store
            if not idempotency_store.mark(dedup_key, source="payment"):
                logger.info("付款交付已发送，跳过重复推送 order=%s", order.get("id"))
                return
        except Exception as e:
            logger.warning(f"付款交付幂等检查失败: {e}")
        try:
            if session_id.startswith("o") and len(session_id) >= 28:
                from core.message_splitter import split_text
                from connectors.wechat_official import official_client
                parts = split_text(content, getattr(settings, "REPLY_MAX_LENGTH", 50))
                split_delay = getattr(settings, "REPLY_SPLIT_DELAY_SECONDS", 1.5)
                for idx, part in enumerate(parts):
                    official_client.send_text(session_id, part)
                    if idx < len(parts) - 1:
                        time.sleep(split_delay)
                logger.info("付款成功已推送交付文档 session=%s 共%s条", session_id, len(parts))
            else:
                logger.info("付款成功，非公众号渠道待人工交付 session=%s", session_id)
                try:
                    from core.sales_crm import crm
                    customer = crm.get_by_session(session_id)
                    if customer:
                        crm.create_notification(customer["id"], target="交付", content=content, status="pending")
                except Exception as notify_err:
                    logger.warning(f"付款交付通知记录失败: {notify_err}")
        except Exception as e:
            logger.error(f"付款成功交付推送失败: {e}")


order_manager = OrderManager()
