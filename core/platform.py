"""PaaS 化：自定义字段、角色权限、团队、审批流查询与 BI 指标"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import CustomField, CustomFieldValue, Role, TeamMember

logger = logging.getLogger(__name__)

ENTITIES = ["customer", "lead", "opportunity", "quote", "contract", "ticket"]
FIELD_TYPES = ["text", "number", "select", "date", "textarea"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class PlatformManager:
    def __init__(self):
        init_db()

    # ---------- 自定义字段 ----------
    def create_field(self, entity, field_name, field_key, field_type="text", options="", required=False, sort=0) -> dict | None:
        entity = entity if entity in ENTITIES else "customer"
        with session_scope() as session:
            existing = session.execute(
                select(CustomField).where(
                    CustomField.entity == entity,
                    CustomField.field_key == field_key,
                )
            ).scalars().first()
            if existing:
                return None
            obj = CustomField(
                entity=entity,
                field_name=field_name or field_key,
                field_key=field_key or "",
                field_type=field_type if field_type in FIELD_TYPES else "text",
                options=options or "",
                required=bool(required),
                enabled=True,
                sort=int(sort or 0),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_fields(self, entity="") -> list[dict]:
        with session_scope() as session:
            query = select(CustomField).order_by(CustomField.entity, CustomField.sort, CustomField.id)
            if entity:
                query = query.where(CustomField.entity == entity)
            rows = session.execute(query).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def update_field(self, field_id: int, **fields) -> dict | None:
        allowed = {"field_name", "field_type", "options", "required", "enabled", "sort"}
        with session_scope() as session:
            obj = session.get(CustomField, field_id)
            if not obj:
                return None
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(obj, key, value)
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def set_values(self, entity, entity_id, values: dict) -> dict:
        entity = entity if entity in ENTITIES else "customer"
        with session_scope() as session:
            for key, value in (values or {}).items():
                obj = session.execute(
                    select(CustomFieldValue).where(
                        CustomFieldValue.entity == entity,
                        CustomFieldValue.entity_id == int(entity_id),
                        CustomFieldValue.field_key == key,
                    )
                ).scalars().first()
                if obj:
                    obj.value = str(value or "")
                    obj.updated_at = _now()
                else:
                    session.add(CustomFieldValue(
                        entity=entity,
                        entity_id=int(entity_id),
                        field_key=key,
                        value=str(value or ""),
                    ))
            target_id = int(entity_id)
        return self.get_values(entity, target_id)

    def get_values(self, entity, entity_id) -> dict:
        with session_scope() as session:
            rows = session.execute(
                select(CustomFieldValue).where(
                    CustomFieldValue.entity == entity,
                    CustomFieldValue.entity_id == int(entity_id),
                )
            ).scalars().all()
            return {r.field_key: r.value for r in rows}

    # ---------- 角色 ----------
    def create_role(self, name, permissions=None, description="") -> dict | None:
        with session_scope() as session:
            existing = session.execute(
                select(Role).where(Role.name == name)
            ).scalars().first()
            if existing:
                return None
            obj = Role(
                name=name or "",
                permissions=json.dumps(permissions or [], ensure_ascii=False),
                description=description or "",
            )
            session.add(obj)
            session.flush()
            return self._role_dict(obj)

    def list_roles(self) -> list[dict]:
        with session_scope() as session:
            rows = session.execute(select(Role).order_by(Role.id)).scalars().all()
            return [self._role_dict(r) for r in rows]

    # ---------- 团队成员 ----------
    def create_member(self, name, nickname="", role="sales", phone="", email="", tenant_id="default") -> dict:
        with session_scope() as session:
            obj = TeamMember(
                tenant_id=tenant_id or "default",
                name=name or "",
                nickname=nickname or "",
                role=role or "sales",
                phone=phone or "",
                email=email or "",
                status="active",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_members(self, tenant_id: str = "", status: str = "") -> list[dict]:
        with session_scope() as session:
            query = select(TeamMember).order_by(TeamMember.id.desc())
            if tenant_id:
                query = query.where(TeamMember.tenant_id == tenant_id)
            if status:
                query = query.where(TeamMember.status == status)
            rows = session.execute(query).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def update_member(self, member_id: int, **fields) -> dict | None:
        allowed = {"name", "nickname", "role", "phone", "email", "status", "tenant_id"}
        with session_scope() as session:
            obj = session.get(TeamMember, member_id)
            if not obj:
                return None
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(obj, key, value)
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    # ---------- BI ----------
    def bi_metrics(self, days: int = 7) -> dict:
        result = {"kpis": {}, "funnel": [], "daily": [], "rates": {}}
        try:
            from core.sales_crm import crm
            customers = crm.list_customers()
            result["kpis"]["customers"] = len(customers)
        except Exception:
            customers = []
        try:
            from core.lead import lead_manager
            leads = lead_manager.stats()
            result["kpis"]["leads"] = leads.get("total", 0)
            result["kpis"]["ocean"] = leads.get("ocean", 0)
            result["kpis"]["won_leads"] = leads.get("won", 0)
        except Exception as e:
            logger.warning("经营看板 线索 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.opportunity import opportunity_manager
            opp = opportunity_manager.stats()
            result["kpis"]["opportunities"] = opp.get("total", 0)
            result["kpis"]["pipeline"] = opp.get("pipeline", 0)
            result["kpis"]["stale_opportunities"] = opp.get("stale", 0)
            result["pipeline_by_stage"] = opp.get("by_stage", {})
        except Exception as e:
            logger.warning("经营看板 商机 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.order import order_manager
            orders = order_manager.stats()
            result["kpis"]["orders"] = orders.get("total_orders", 0)
            result["kpis"]["revenue"] = orders.get("paid_amount", 0)
        except Exception as e:
            logger.warning("经营看板 订单 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.finance import finance_manager
            fin = finance_manager.stats()
            result["kpis"]["outstanding"] = fin.get("outstanding", 0)
            result["kpis"]["overdue_receivables"] = fin.get("overdue", 0)
        except Exception as e:
            logger.warning("经营看板 财务 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.followup import followup_engine
            fu = followup_engine.stats()
            result["kpis"]["pending_followups"] = fu.get("pending", 0)
        except Exception as e:
            logger.warning("经营看板 跟进 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.ticket import ticket_manager
            tk = ticket_manager.stats()
            result["kpis"]["open_tickets"] = tk.get("open", 0) + tk.get("processing", 0)
            result["kpis"]["overdue_tickets"] = tk.get("overdue", 0)
        except Exception as e:
            logger.warning("经营看板 工单 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.quality import quality_checker
            qa = quality_checker.stats()
            result["kpis"]["quality_avg"] = qa.get("avg_score", 0)
        except Exception as e:
            logger.warning("经营看板 质检 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.marketing import marketing_manager
            mk = marketing_manager.stats()
            result["kpis"]["campaigns"] = mk.get("campaigns", 0)
            result["kpis"]["ad_roi"] = mk.get("roi", 0)
        except Exception as e:
            logger.warning("经营看板 营销 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.portrait import portrait_manager
            result["kpis"]["risk_events"] = len(portrait_manager.list_risks(limit=100000))
        except Exception as e:
            logger.warning("经营看板 风险 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.cpq import cpq_manager
            cpq = cpq_manager.stats()
            result["kpis"]["quotes"] = cpq.get("quotes", 0)
            result["kpis"]["contracts"] = cpq.get("contracts", 0)
            result["kpis"]["approvals_pending"] = cpq.get("approvals_pending", 0)
        except Exception as e:
            logger.warning("经营看板 报价合同 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            result["kpis"]["team"] = len(self.list_members())
        except Exception as e:
            logger.warning("经营看板 团队成员 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            result["kpis"]["custom_fields"] = len(self.list_fields())
        except Exception as e:
            logger.warning("经营看板 自定义字段 指标采集失败，该部分会显示为 0/空: %s", e)

        stage_labels = {
            "new": "陌生",
            "understanding": "兴趣了解",
            "recommended": "意向明确",
            "high_intent": "高意向",
            "enrolled": "已报名",
            "won": "已成交",
            "after_sales": "售后",
            "lost": "流失",
        }
        stage_counts = {}
        for c in customers:
            stage = c.get("stage") or "new"
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        total = max(len(customers), 1)
        result["funnel"] = [
            {"stage": s, "label": stage_labels.get(s, s), "count": stage_counts.get(s, 0),
             "ratio": round(stage_counts.get(s, 0) / total * 100, 1)}
            for s in ("new", "understanding", "recommended", "high_intent", "enrolled", "won", "after_sales")
        ]
        result["kpis"]["high_intent"] = stage_counts.get("high_intent", 0) + stage_counts.get("enrolled", 0) + stage_counts.get("won", 0)
        result["kpis"]["won"] = stage_counts.get("won", 0)
        result["rates"] = {
            "l3_rate": round((stage_counts.get("recommended", 0) + stage_counts.get("high_intent", 0) +
                              stage_counts.get("enrolled", 0) + stage_counts.get("won", 0)) / total * 100, 1),
            "won_rate": round(stage_counts.get("won", 0) / total * 100, 1),
        }

        cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        daily = {}
        for c in customers:
            created = (c.get("created_at") or "")[:10]
            if created >= cutoff:
                daily[created] = daily.get(created, 0) + 1
        result["daily"] = [{"date": d, "count": daily[d]} for d in sorted(daily)]
        return result

    @staticmethod
    def _role_dict(obj) -> dict:
        result = _row_to_dict(obj)
        try:
            result["permissions"] = json.loads(result.get("permissions") or "[]")
        except (TypeError, ValueError):
            result["permissions"] = []
        return result


platform_manager = PlatformManager()
