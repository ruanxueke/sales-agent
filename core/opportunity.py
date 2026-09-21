"""商机管理：金额、预计成交、赢率、阶段、停滞预警与赢率预测"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from config.settings import settings
from core.db import init_db, session_scope
from core.models import Opportunity

logger = logging.getLogger(__name__)

OPPORTUNITY_STAGES = ["qualifying", "proposal", "negotiation", "won", "lost"]
OPPORTUNITY_STAGE_LABELS = {
    "qualifying": "需求确认",
    "proposal": "方案报价",
    "negotiation": "商务谈判",
    "won": "赢单",
    "lost": "输单",
}
STAGE_WEIGHTS = {
    "qualifying": 0.2,
    "proposal": 0.5,
    "negotiation": 0.75,
    "won": 1.0,
    "lost": 0.0,
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _datetime_plus(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _normalize_stage(stage: str) -> str:
    return stage if stage in OPPORTUNITY_STAGES else "qualifying"


class OpportunityManager:
    def __init__(self):
        init_db()

    def create(
        self,
        name: str,
        customer_id: int = None,
        lead_id: int = None,
        session_id: str = "",
        product_name: str = "",
        amount: float = 0,
        stage: str = "qualifying",
        win_rate: int = 0,
        owner: str = "",
        source: str = "",
        expected_close_at: str = "",
        notes: str = "",
    ) -> dict:
        with session_scope() as session:
            obj = Opportunity(
                name=name or "未命名商机",
                customer_id=customer_id,
                lead_id=lead_id,
                session_id=session_id or "",
                product_name=product_name or "",
                amount=float(amount or 0),
                stage=_normalize_stage(stage),
                win_rate=max(0, min(100, int(win_rate or 0))),
                owner=owner or settings.LEAD_DEFAULT_OWNER or "",
                source=source or "",
                expected_close_at=expected_close_at or "",
                last_activity_at=_now(),
                risk_level="low",
                risk_reason="",
                notes=notes or "",
            )
            session.add(obj)
            session.flush()
            return self._enrich(_row_to_dict(obj))

    def get(self, opportunity_id: int) -> dict | None:
        with session_scope() as session:
            obj = session.get(Opportunity, opportunity_id)
            return self._enrich(_row_to_dict(obj)) if obj else None

    def list(
        self,
        stage: str = "",
        owner: str = "",
        keyword: str = "",
        risk: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        with session_scope() as session:
            query = select(Opportunity).order_by(Opportunity.id.desc()).offset(offset).limit(limit)
            if stage:
                query = query.where(Opportunity.stage == stage)
            if owner:
                query = query.where(Opportunity.owner == owner)
            if risk:
                query = query.where(Opportunity.risk_level == risk)
            if keyword:
                like = f"%{keyword}%"
                query = query.where(or_(
                    Opportunity.name.like(like),
                    Opportunity.product_name.like(like),
                    Opportunity.session_id.like(like),
                    Opportunity.owner.like(like),
                ))
            rows = session.execute(query).scalars().all()
            return [self._enrich(_row_to_dict(r)) for r in rows]

    def update(self, opportunity_id: int, **fields) -> dict | None:
        allowed = {
            "name", "product_name", "amount", "win_rate", "owner", "source",
            "expected_close_at", "loss_reason", "notes",
        }
        with session_scope() as session:
            obj = session.get(Opportunity, opportunity_id)
            if not obj:
                return None
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(obj, key, value)
            obj.updated_at = _now()
            obj.last_activity_at = _now()
            session.flush()
            return self._enrich(_row_to_dict(obj))

    def mark_stage(
        self,
        opportunity_id: int,
        stage: str,
        loss_reason: str = "",
    ) -> dict | None:
        stage = _normalize_stage(stage)
        with session_scope() as session:
            obj = session.get(Opportunity, opportunity_id)
            if not obj:
                return None
            obj.stage = stage
            obj.updated_at = _now()
            obj.last_activity_at = _now()
            if stage == "won":
                obj.win_rate = 100
                obj.risk_level = "low"
                obj.risk_reason = ""
                obj.loss_reason = ""
            elif stage == "lost":
                obj.win_rate = 0
                obj.risk_level = "low"
                obj.risk_reason = ""
                obj.loss_reason = loss_reason or obj.loss_reason or ""
            session.flush()
            result = self._enrich(_row_to_dict(obj))

        if stage == "won":
            self._on_won(result)
        return result

    def _on_won(self, opportunity: dict) -> None:
        try:
            if opportunity.get("lead_id"):
                from core.lead import lead_manager
                lead_manager.mark_status(opportunity["lead_id"], "won")
        except Exception as e:
            logger.error(f"商机赢单后更新线索失败: {e}")

    def predict_win_rate(self, opportunity_id: int) -> dict | None:
        with session_scope() as session:
            obj = session.get(Opportunity, opportunity_id)
            if not obj:
                return None
            base = STAGE_WEIGHTS.get(obj.stage, 0.2) * 100
            intent_bonus = 0
            recency_bonus = 0
            lead = None
            if obj.lead_id:
                try:
                    from core.lead import lead_manager
                    lead = lead_manager.get(obj.lead_id)
                except Exception:
                    lead = None
            if lead:
                intent_bonus = min(15, int(lead.get("intent_score") or 0) / 10)
            try:
                last = datetime.strptime(obj.last_activity_at or _now(), "%Y-%m-%d %H:%M:%S")
                days_stale = (datetime.now() - last).days
                if days_stale <= 1:
                    recency_bonus = 8
                elif days_stale <= 3:
                    recency_bonus = 3
            except ValueError as e:
                logger.debug("OpportunityManager.predict_win_rate 异常已忽略: %s", e)
            predicted = max(0, min(100, int(round(base + intent_bonus + recency_bonus))))
            obj.win_rate = predicted
            obj.updated_at = _now()
            session.flush()
            return {
                **self._enrich(_row_to_dict(obj)),
                "predicted_win_rate": predicted,
                "base_by_stage": round(base, 1),
                "intent_bonus": intent_bonus,
                "recency_bonus": recency_bonus,
            }

    def refresh_risk(self, stale_days: int = 3) -> dict:
        stale_days = max(1, int(stale_days or 3))
        cutoff = (datetime.now() - timedelta(days=stale_days)).strftime("%Y-%m-%d %H:%M:%S")
        with session_scope() as session:
            rows = session.execute(
                select(Opportunity).where(
                    Opportunity.stage.notin_(["won", "lost"]),
                )
            ).scalars().all()
            updated = 0
            for obj in rows:
                reason_parts = []
                risk = "low"
                if (obj.last_activity_at or "") < cutoff:
                    risk = "high"
                    reason_parts.append(f"超过 {stale_days} 天无跟进")
                if obj.expected_close_at and obj.expected_close_at < _now():
                    risk = "high" if risk == "low" else risk
                    reason_parts.append("已过预计成交时间")
                if risk != obj.risk_level or (reason_parts and obj.risk_reason != "；".join(reason_parts)):
                    obj.risk_level = risk
                    obj.risk_reason = "；".join(reason_parts)
                    obj.updated_at = _now()
                    updated += 1
            return {"checked": len(rows), "updated": updated}

    def stats(self) -> dict:
        items = self.list(limit=100000)
        by_stage = {s: {"count": 0, "amount": 0.0} for s in OPPORTUNITY_STAGES}
        total_pipeline = 0.0
        won_amount = 0.0
        stale = 0
        for item in items:
            stage = item.get("stage") or "qualifying"
            amount = float(item.get("amount") or 0)
            by_stage.setdefault(stage, {"count": 0, "amount": 0.0})
            by_stage[stage]["count"] += 1
            by_stage[stage]["amount"] += amount
            if stage not in ("won", "lost"):
                total_pipeline += amount
            if stage == "won":
                won_amount += amount
            if item.get("risk_level") == "high":
                stale += 1
        return {
            "total": len(items),
            "pipeline": round(total_pipeline, 2),
            "won_amount": round(won_amount, 2),
            "stale": stale,
            "by_stage": {k: {"count": v["count"], "amount": round(v["amount"], 2)} for k, v in by_stage.items()},
        }

    @staticmethod
    def _enrich(item: dict) -> dict:
        item["stage_label"] = OPPORTUNITY_STAGE_LABELS.get(item.get("stage") or "", item.get("stage") or "")
        return item


opportunity_manager = OpportunityManager()
