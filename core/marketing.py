"""营销活动、广告 ROI 与复购计划"""
from __future__ import annotations
import logging
from datetime import datetime

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import AdMetric, Campaign, RepurchasePlan

logger = logging.getLogger(__name__)

CAMPAIGN_STATUSES = ["draft", "running", "paused", "finished", "cancelled"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class MarketingManager:
    def __init__(self):
        init_db()

    # ---------- 营销活动 ----------
    def create_campaign(self, name, channel="official", budget=0, cost=0, start_at="", end_at="", target="", description="") -> dict:
        with session_scope() as session:
            obj = Campaign(
                name=name or "未命名活动",
                channel=channel or "official",
                status="draft",
                budget=float(budget or 0),
                cost=float(cost or 0),
                start_at=start_at or "",
                end_at=end_at or "",
                target=target or "",
                description=description or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_campaign(self, campaign_id: int, **fields) -> dict | None:
        allowed = {"name", "channel", "status", "budget", "cost", "start_at", "end_at", "target", "description"}
        with session_scope() as session:
            obj = session.get(Campaign, campaign_id)
            if not obj:
                return None
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(obj, key, value)
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def list_campaigns(self, status="", channel="", limit=500) -> list[dict]:
        with session_scope() as session:
            query = select(Campaign).order_by(Campaign.id.desc())
            if status:
                query = query.where(Campaign.status == status)
            if channel:
                query = query.where(Campaign.channel == channel)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 广告指标 ----------
    def upsert_ad_metric(
        self,
        campaign_id: int,
        metric_date: str,
        impressions: int = 0,
        clicks: int = 0,
        conversions: int = 0,
        cost: float = 0,
        revenue: float = 0,
    ) -> dict | None:
        with session_scope() as session:
            obj = session.execute(
                select(AdMetric).where(
                    AdMetric.campaign_id == campaign_id,
                    AdMetric.metric_date == metric_date,
                )
            ).scalars().first()
            if not obj:
                obj = AdMetric(campaign_id=campaign_id, metric_date=metric_date or "")
                session.add(obj)
            obj.impressions = int(impressions or 0)
            obj.clicks = int(clicks or 0)
            obj.conversions = int(conversions or 0)
            obj.cost = float(cost or 0)
            obj.revenue = float(revenue or 0)
            obj.updated_at = _now()
            session.flush()
            return self._enrich_metric(_row_to_dict(obj))

    def list_ad_metrics(self, campaign_id: int = 0, limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(AdMetric).order_by(AdMetric.metric_date.desc(), AdMetric.id.desc())
            if campaign_id:
                query = query.where(AdMetric.campaign_id == campaign_id)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [self._enrich_metric(_row_to_dict(r)) for r in rows]

    # ---------- 复购计划 ----------
    def create_repurchase(
        self,
        product_name: str,
        plan_date: str = "",
        session_id: str = "",
        customer_id: int = None,
        lead_id: int = None,
        order_id: int = None,
        note: str = "",
    ) -> dict:
        with session_scope() as session:
            obj = RepurchasePlan(
                session_id=session_id or "",
                customer_id=customer_id,
                lead_id=lead_id,
                order_id=order_id,
                product_name=product_name or "",
                plan_date=plan_date or "",
                status="pending",
                note=note or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_repurchase(self, plan_id: int, status: str = "", plan_date: str = "", note: str = "") -> dict | None:
        with session_scope() as session:
            obj = session.get(RepurchasePlan, plan_id)
            if not obj:
                return None
            if status:
                obj.status = status
            if plan_date:
                obj.plan_date = plan_date
            if note:
                obj.note = note
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def list_repurchases(self, status: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(RepurchasePlan).order_by(RepurchasePlan.plan_date, RepurchasePlan.id.desc())
            if status:
                query = query.where(RepurchasePlan.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def dispatch_due_repurchases(self, limit: int = 50) -> int:
        """到期的复购计划生成一条跟进任务，交给自动跟进通道发送"""
        now = _now()
        with session_scope() as session:
            rows = session.execute(
                select(RepurchasePlan)
                .where(RepurchasePlan.status == "pending", RepurchasePlan.plan_date != "", RepurchasePlan.plan_date <= now)
                .order_by(RepurchasePlan.plan_date)
                .limit(limit)
            ).scalars().all()
            created = 0
            for plan in rows:
                try:
                    from core.followup import followup_engine
                    from core.models import FollowupTask
                    from core.sales_crm import crm
                    customer = crm.get(plan.customer_id) if plan.customer_id else crm.get_by_session(plan.session_id)
                    source = (customer or {}).get("source") or "wechat"
                    channel = "official" if source == "official" else "wechat"
                    nickname = (customer or {}).get("nickname") or (customer or {}).get("name") or ""
                    content = f"您好{nickname}，{plan.product_name or '相关产品'}到了再次了解的好时机，方便聊聊近况和需求吗？"
                    session.add(FollowupTask(
                        session_id=plan.session_id or "",
                        lead_id=plan.lead_id,
                        customer_id=plan.customer_id,
                        node=1,
                        node_label="repurchase",
                        due_at=now,
                        status="pending",
                        channel=channel,
                        content=content,
                    ))
                    plan.status = "dispatched"
                    plan.updated_at = now
                    created += 1
                except Exception as e:
                    logger.error(f"复购计划派发失败 #{plan.id}: {e}")
            return created

    def stats(self) -> dict:
        campaigns = self.list_campaigns(limit=100000)
        metrics = self.list_ad_metrics(limit=100000)
        repurchases = self.list_repurchases(limit=100000)
        total_budget = sum(float(c.get("budget") or 0) for c in campaigns)
        total_cost = sum(float(m.get("cost") or 0) for m in metrics)
        total_revenue = sum(float(m.get("revenue") or 0) for m in metrics)
        total_clicks = sum(int(m.get("clicks") or 0) for m in metrics)
        total_conversions = sum(int(m.get("conversions") or 0) for m in metrics)
        total_impressions = sum(int(m.get("impressions") or 0) for m in metrics)
        return {
            "campaigns": len(campaigns),
            "running": sum(1 for c in campaigns if c.get("status") == "running"),
            "budget": round(total_budget, 2),
            "cost": round(total_cost, 2),
            "revenue": round(total_revenue, 2),
            "roi": round((total_revenue - total_cost) / total_cost, 2) if total_cost else 0.0,
            "ctr": round(total_clicks / total_impressions * 100, 2) if total_impressions else 0.0,
            "cvr": round(total_conversions / total_clicks * 100, 2) if total_clicks else 0.0,
            "cpa": round(total_cost / total_conversions, 2) if total_conversions else 0.0,
            "impressions": total_impressions,
            "clicks": total_clicks,
            "conversions": total_conversions,
            "repurchases": len(repurchases),
            "repurchases_pending": sum(1 for r in repurchases if r.get("status") == "pending"),
        }

    @staticmethod
    def _enrich_metric(item: dict) -> dict:
        impressions = int(item.get("impressions") or 0)
        clicks = int(item.get("clicks") or 0)
        conversions = int(item.get("conversions") or 0)
        cost = float(item.get("cost") or 0)
        revenue = float(item.get("revenue") or 0)
        item["ctr"] = round(clicks / impressions * 100, 2) if impressions else 0.0
        item["cvr"] = round(conversions / clicks * 100, 2) if clicks else 0.0
        item["cpa"] = round(cost / conversions, 2) if conversions else 0.0
        item["roi"] = round((revenue - cost) / cost, 2) if cost else 0.0
        return item


marketing_manager = MarketingManager()
