"""动态意向评分：多触点行为事件实时累加，热度变化驱动跟进优先级"""
from __future__ import annotations
import logging

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import BehaviorEvent
from core.sales_extract import compute_intent_level

logger = logging.getLogger(__name__)

EVENT_WEIGHTS = {
    "page_view": 2,
    "doc_download": 5,
    "quote_view": 8,
    "wechat_message": 1,
    "voice_call": 6,
    "form_submit": 10,
    "payment_intent": 12,
}

EVENT_LABELS = {
    "page_view": "浏览页面",
    "doc_download": "下载资料",
    "quote_view": "查看报价",
    "wechat_message": "微信互动",
    "voice_call": "语音沟通",
    "form_submit": "提交表单",
    "payment_intent": "付款意向",
}


class ScoreEngine:
    def record_event(
        self,
        session_id: str,
        event_type: str,
        event_value: str = "",
        source: str = "",
    ) -> dict:
        init_db()
        weight = EVENT_WEIGHTS.get(event_type, 1)
        lead = None
        customer = None
        try:
            from core.lead import lead_manager
            lead = lead_manager.get_by_session_id(session_id)
        except Exception as e:
            logger.debug("ScoreEngine.record_event 异常已忽略: %s", e)
        try:
            from core.sales_crm import crm
            customer = crm.get_by_session(session_id)
        except Exception as e:
            logger.debug("ScoreEngine.record_event 异常已忽略: %s", e)

        with session_scope() as session:
            session.add(BehaviorEvent(
                session_id=session_id,
                lead_id=lead["id"] if lead else None,
                event_type=event_type,
                event_value=event_value[:128],
                score=weight,
            ))

        if lead:
            new_score = min(100, int(lead.get("intent_score") or 0) + weight)
            intent_level = compute_intent_level(lead.get("stage") or "new", new_score)
            try:
                from core.lead import lead_manager
                lead_manager.update(
                    lead["id"],
                    intent_score=new_score,
                    intent_level=intent_level,
                )
            except Exception as e:
                logger.error(f"线索评分更新失败: {e}")
        if customer:
            new_score = min(100, int(customer.get("intent_score") or 0) + weight)
            intent_level = compute_intent_level(customer.get("stage") or "new", new_score)
            try:
                from core.sales_crm import crm
                crm.update_profile(
                    customer["id"],
                    intent_score=new_score,
                    intent_level=intent_level,
                )
            except Exception as e:
                logger.error(f"客户评分更新失败: {e}")

        return {
            "session_id": session_id,
            "event_type": event_type,
            "weight": weight,
            "score": max(
                int(customer.get("intent_score") or 0) if customer else 0,
                int(lead.get("intent_score") or 0) if lead else 0,
                weight,
            ),
        }

    def list_events(self, session_id: str, limit: int = 100) -> list[dict]:
        init_db()
        with session_scope() as session:
            rows = session.execute(
                select(BehaviorEvent)
                .where(BehaviorEvent.session_id == session_id)
                .order_by(BehaviorEvent.id.desc())
                .limit(limit)
            ).scalars().all()
            return [
                {
                    **{c.name: getattr(r, c.name) for c in r.__table__.columns},
                    "event_label": EVENT_LABELS.get(r.event_type, r.event_type),
                }
                for r in rows
            ]

    def stats(self) -> dict:
        init_db()
        with session_scope() as session:
            rows = session.execute(select(BehaviorEvent)).scalars().all()
        by_type = {}
        total = 0
        for row in rows:
            by_type[row.event_type] = by_type.get(row.event_type, 0) + 1
            total += 1
        return {
            "total_events": total,
            "by_type": by_type,
            "labels": EVENT_LABELS,
        }


score_engine = ScoreEngine()
