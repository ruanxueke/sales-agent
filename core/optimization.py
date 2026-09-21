"""优化与复盘：会话指标统计、A/B 实验、周复盘"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import AbExperiment, AbRun, WeeklyReview

logger = logging.getLogger(__name__)

AB_KINDS = ["script", "timing", "hook", "benefit"]
AB_STATUSES = ["draft", "running", "paused", "finished"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class OptimizationManager:
    def __init__(self):
        init_db()

    # ---------- A/B 实验 ----------
    def create_experiment(self, name: str, kind: str = "script", control: str = "", variant: str = "", note: str = "") -> dict:
        kind = kind if kind in AB_KINDS else "script"
        with session_scope() as session:
            obj = AbExperiment(
                name=name or "未命名实验",
                kind=kind,
                control=control or "",
                variant=variant or "",
                status="draft",
                note=note or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_experiment(self, experiment_id: int, **fields) -> dict | None:
        allowed = {"name", "kind", "control", "variant", "status", "start_at", "end_at", "note"}
        with session_scope() as session:
            obj = session.get(AbExperiment, experiment_id)
            if not obj:
                return None
            for k, v in fields.items():
                if k in allowed and v is not None:
                    setattr(obj, k, v)
            if obj.status == "running" and not obj.start_at:
                obj.start_at = _now()
            return _row_to_dict(obj)

    def list_experiments(self, status: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(AbExperiment).order_by(AbExperiment.id.desc())
            if status:
                query = query.where(AbExperiment.status == status)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    def record_run(self, experiment_id: int, session_id: str, variant: str = "control", result: str = "") -> dict | None:
        with session_scope() as session:
            obj = session.get(AbExperiment, experiment_id)
            if not obj:
                return None
            run = AbRun(
                experiment_id=experiment_id,
                session_id=session_id or "",
                variant=variant if variant in ("control", "variant") else "control",
                result=result or "",
            )
            session.add(run)
            session.flush()
            return _row_to_dict(run)

    def list_runs(self, experiment_id: int = 0, limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(AbRun).order_by(AbRun.id.desc())
            if experiment_id:
                query = query.where(AbRun.experiment_id == experiment_id)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    # ---------- 周复盘 ----------
    def create_review(self, content: str, week_start: str = "") -> dict:
        if not week_start:
            week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
        metrics = self.metric_summary()
        with session_scope() as session:
            obj = WeeklyReview(
                week_start=week_start,
                content=content or "",
                metrics_json=json.dumps(metrics, ensure_ascii=False),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_reviews(self, limit: int = 50) -> list[dict]:
        with session_scope() as session:
            rows = session.execute(select(WeeklyReview).order_by(WeeklyReview.id.desc()).limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 指标 ----------
    def metric_summary(self, days: int = 7) -> dict:
        from core.conversation import conversation_manager
        stats = conversation_manager.stats()
        from core.followup import followup_engine
        followup_stats = followup_engine.stats()
        from core.order import order_manager
        order_stats = order_manager.stats()
        from core.lead import lead_manager
        lead_stats = lead_manager.stats()

        metrics = conversation_manager.list_metrics(limit=100000)
        cutoff = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
        recent = [m for m in metrics if (m.get("created_at") or "").startswith(tuple(
            (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)
        ))]
        reply_count = len(recent)
        followup_result_counts = {}
        for m in recent:
            r = m.get("followup_result") or ""
            if r:
                followup_result_counts[r] = followup_result_counts.get(r, 0) + 1
        return {
            "period_days": days,
            "conversations": reply_count,
            "next_step_rate": stats.get("next_step_rate", 0),
            "evidence_rate": stats.get("evidence_rate", 0),
            "deal_count": order_stats.get("paid_orders", 0),
            "new_leads": lead_stats.get("week_new", 0),
            "pending_followups": followup_stats.get("pending", 0),
            "followup_results": followup_result_counts,
            "conversion_status": stats.get("by_status", {}),
            "concern_distribution": stats.get("by_concern", {}),
        }

    def stats(self) -> dict:
        experiments = self.list_experiments(limit=100000)
        reviews = self.list_reviews(limit=100000)
        runs = self.list_runs(limit=100000)
        return {
            "experiments": len(experiments),
            "running": sum(1 for e in experiments if e.get("status") == "running"),
            "finished": sum(1 for e in experiments if e.get("status") == "finished"),
            "runs": len(runs),
            "reviews": len(reviews),
            "summary": self.metric_summary(),
        }



    def delete_experiment(self, experiment_id: int) -> bool:
        with session_scope() as session:
            obj = session.get(AbExperiment, experiment_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_review(self, review_id: int) -> bool:
        with session_scope() as session:
            obj = session.get(WeeklyReview, review_id)
            if not obj:
                return False
            session.delete(obj)
            return True


optimization_manager = OptimizationManager()
