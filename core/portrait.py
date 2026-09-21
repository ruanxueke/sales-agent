"""360° 客户画像：工商信息、干系人图谱、舆情风险、跨渠道动线"""
from __future__ import annotations
import logging
from datetime import datetime

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import (
    BusinessProfile,
    ChannelJourney,
    CustomerTag,
    RiskEvent,
    Stakeholder,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class PortraitManager:
    def __init__(self):
        init_db()

    # ---------- 工商信息 ----------
    def upsert_business_profile(
        self,
        session_id: str = "",
        customer_id: int = None,
        lead_id: int = None,
        **fields,
    ) -> dict:
        allowed = {
            "company_name", "unified_code", "legal_person", "registered_capital",
            "industry", "address", "risk_summary",
        }
        with session_scope() as session:
            obj = self._find(session, BusinessProfile, session_id, customer_id, lead_id)
            data = {k: v for k, v in fields.items() if k in allowed}
            if obj:
                for key, value in data.items():
                    if value is not None:
                        setattr(obj, key, value)
                obj.updated_at = _now()
                session.flush()
                return _row_to_dict(obj)
            obj = BusinessProfile(
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                **data,
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    # ---------- 干系人 ----------
    def add_stakeholder(
        self,
        session_id: str = "",
        customer_id: int = None,
        lead_id: int = None,
        **fields,
    ) -> dict:
        with session_scope() as session:
            obj = Stakeholder(
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                name=fields.get("name") or "",
                role=fields.get("role") or "",
                relation=fields.get("relation") or "",
                company=fields.get("company") or "",
                phone=fields.get("phone") or "",
                wechat_id=fields.get("wechat_id") or "",
                influence=fields.get("influence") or "medium",
                notes=fields.get("notes") or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    # ---------- 标签 ----------
    def add_tag(
        self,
        tag: str,
        session_id: str = "",
        customer_id: int = None,
        lead_id: int = None,
        source: str = "manual",
    ) -> dict | None:
        tag = (tag or "").strip()
        if not tag:
            return None
        with session_scope() as session:
            existing = session.execute(
                select(CustomerTag).where(
                    CustomerTag.tag == tag,
                    CustomerTag.session_id == (session_id or ""),
                )
            ).scalars().first()
            if existing:
                return _row_to_dict(existing)
            obj = CustomerTag(
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                tag=tag,
                source=source or "manual",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    # ---------- 风险事件 ----------
    def add_risk(
        self,
        risk_type: str,
        level: str,
        content: str,
        session_id: str = "",
        customer_id: int = None,
        lead_id: int = None,
        source: str = "manual",
    ) -> dict:
        with session_scope() as session:
            obj = RiskEvent(
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                risk_type=risk_type or "",
                level=level if level in ("high", "medium", "low") else "medium",
                content=content or "",
                source=source or "manual",
                status="open",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_risk_status(self, risk_id: int, status: str) -> dict | None:
        with session_scope() as session:
            obj = session.get(RiskEvent, risk_id)
            if not obj:
                return None
            obj.status = status
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    # ---------- 跨渠道动线 ----------
    def add_journey(
        self,
        channel: str,
        action: str,
        detail: str = "",
        session_id: str = "",
        customer_id: int = None,
        lead_id: int = None,
    ) -> dict:
        with session_scope() as session:
            obj = ChannelJourney(
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                channel=channel or "",
                action=action or "",
                detail=detail or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_risks(self, status: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(RiskEvent).order_by(RiskEvent.id.desc())
            if status:
                query = query.where(RiskEvent.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 聚合画像 ----------
    def portrait(self, session_id: str = "", customer_id: int = None, lead_id: int = None) -> dict:
        with session_scope() as session:
            customer = None
            lead = None
            if customer_id:
                from core.sales_crm import crm
                customer = crm.get(customer_id)
                session_id = session_id or (customer or {}).get("session_id", "")
            if lead_id:
                from core.lead import lead_manager
                lead = lead_manager.get(lead_id)
                session_id = session_id or (lead or {}).get("session_id", "")
            if session_id and not customer:
                try:
                    from core.sales_crm import crm
                    customer = crm.get_by_session(session_id)
                    customer_id = (customer or {}).get("id")
                except Exception:
                    customer = None
            if session_id and not lead:
                try:
                    from core.lead import lead_manager
                    lead = lead_manager.get_by_session_id(session_id)
                    lead_id = (lead or {}).get("id")
                except Exception:
                    lead = None

            result = {
                "customer": customer,
                "lead": lead,
                "business_profile": None,
                "stakeholders": [],
                "tags": [],
                "risks": [],
                "journey": [],
                "orders": [],
                "opportunities": [],
                "tickets": [],
                "visits": [],
                "custom_fields": {},
            }
            if customer_id or session_id:
                result["business_profile"] = self._find(
                    session, BusinessProfile, session_id, customer_id, None
                )
                if result["business_profile"]:
                    result["business_profile"] = _row_to_dict(result["business_profile"])
                result["stakeholders"] = self._list_model(
                    session, Stakeholder, session_id, customer_id, None
                )
                result["tags"] = self._list_model(session, CustomerTag, session_id, customer_id, None)
                result["risks"] = self._list_model(session, RiskEvent, session_id, customer_id, None)
                result["journey"] = self._list_model(session, ChannelJourney, session_id, customer_id, None)
                try:
                    from core.order import order_manager
                    all_orders = order_manager.list_orders(limit=1000)
                    if customer_id:
                        result["orders"] = [o for o in all_orders if o.get("customer_id") == customer_id]
                    else:
                        result["orders"] = [o for o in all_orders if o.get("session_id") == session_id]
                except Exception as e:
                    logger.warning("经营看板 订单 指标采集失败，该部分会显示为 0/空: %s", e)
                try:
                    from core.opportunity import opportunity_manager
                    result["opportunities"] = opportunity_manager.list(limit=1000)
                    result["opportunities"] = [
                        o for o in result["opportunities"]
                        if o.get("customer_id") == customer_id or o.get("session_id") == session_id
                    ]
                except Exception as e:
                    logger.warning("经营看板 商机 指标采集失败，该部分会显示为 0/空: %s", e)
                try:
                    from core.ticket import ticket_manager
                    result["tickets"] = ticket_manager.list_for_session(session_id, limit=100)
                except Exception as e:
                    logger.warning("经营看板 工单 指标采集失败，该部分会显示为 0/空: %s", e)
                try:
                    from core.ticket import ticket_manager
                    result["visits"] = ticket_manager.list_visits(session_id=session_id, limit=100)
                except Exception as e:
                    logger.warning("经营看板 访问记录 指标采集失败，该部分会显示为 0/空: %s", e)
                try:
                    from core.platform import platform_manager
                    if customer_id:
                        result["custom_fields"] = platform_manager.get_values("customer", customer_id)
                except Exception as e:
                    logger.warning("经营看板 自定义字段 指标采集失败，该部分会显示为 0/空: %s", e)
            return result

    def auto_scan_risks(self) -> dict:
        created = 0
        try:
            from core.finance import finance_manager
            existing_open = {
                (r.get("risk_type"), r.get("content"))
                for r in self.list_risks(status="open", limit=100000)
            }
            for r in finance_manager.list_receivables(status="overdue", limit=1000):
                customer_id = None
                session_id = ""
                try:
                    from core.order import order_manager
                    orders = order_manager.list_orders(limit=100000)
                    order = next((o for o in orders if o.get("id") == r.get("order_id")), None)
                    if order:
                        customer_id = order.get("customer_id")
                        session_id = order.get("session_id") or ""
                except Exception as e:
                    logger.warning("经营看板 订单归属 指标采集失败，该部分会显示为 0/空: %s", e)
                content = f"订单 #{r.get('order_id')} 应收 {r.get('amount')} 元已逾期"
                if ("应收逾期", content) in existing_open:
                    continue
                self.add_risk(
                    risk_type="应收逾期",
                    level="high",
                    content=content,
                    session_id=session_id,
                    customer_id=customer_id,
                    lead_id=None,
                    source="auto",
                )
                created += 1
        except Exception as e:
            logger.error(f"应收逾期风险扫描失败: {e}")
        return {"created": created}

    @staticmethod
    def _find(session, model, session_id: str, customer_id: int = None, lead_id: int = None):
        query = None
        if session_id:
            query = select(model).where(model.session_id == session_id)
        elif customer_id:
            query = select(model).where(model.customer_id == customer_id)
        elif lead_id:
            query = select(model).where(model.lead_id == lead_id)
        if query is None:
            return None
        return session.execute(query).scalars().first()

    @staticmethod
    def _list_model(session, model, session_id: str, customer_id: int = None, lead_id: int = None) -> list[dict]:
        query = None
        if session_id:
            query = select(model).where(model.session_id == session_id)
        elif customer_id:
            query = select(model).where(model.customer_id == customer_id)
        elif lead_id:
            query = select(model).where(model.lead_id == lead_id)
        if query is None:
            return []
        rows = session.execute(query).scalars().all()
        return [_row_to_dict(r) for r in rows]


portrait_manager = PortraitManager()
