"""可配置销售 SOP：模板、阶段步骤、执行记录与执行率统计"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import SopExecution, SopTemplate

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _datetime_plus_hours(hours: int) -> str:
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class SopManager:
    def __init__(self):
        init_db()

    def create_template(self, name: str, stage: str, steps: list[dict]) -> dict:
        with session_scope() as session:
            obj = SopTemplate(
                name=name or "未命名SOP",
                stage=stage or "",
                steps_json=json.dumps(steps or [], ensure_ascii=False),
                active=True,
            )
            session.add(obj)
            session.flush()
            return self._template_dict(obj)

    def list_templates(self, stage: str = "", active_only: bool = False) -> list[dict]:
        with session_scope() as session:
            query = select(SopTemplate).order_by(SopTemplate.id.desc())
            if stage:
                query = query.where(SopTemplate.stage == stage)
            if active_only:
                query = query.where(SopTemplate.active.is_(True))
            rows = session.execute(query).scalars().all()
            return [self._template_dict(r) for r in rows]

    def update_template(self, template_id: int, name: str = "", stage: str = "", steps=None, active=None) -> dict | None:
        with session_scope() as session:
            obj = session.get(SopTemplate, template_id)
            if not obj:
                return None
            if name:
                obj.name = name
            if stage:
                obj.stage = stage
            if steps is not None:
                obj.steps_json = json.dumps(steps, ensure_ascii=False)
            if active is not None:
                obj.active = bool(active)
            obj.updated_at = _now()
            session.flush()
            return self._template_dict(obj)

    def start_execution(self, template_id: int, session_id: str = "", customer_id: int = None, lead_id: int = None) -> dict | None:
        with session_scope() as session:
            template = session.get(SopTemplate, template_id)
            if not template or not template.active:
                return None
            try:
                steps = json.loads(template.steps_json or "[]")
            except (TypeError, ValueError):
                steps = []
            if not steps:
                return None
            existing = session.execute(
                select(SopExecution).where(
                    SopExecution.template_id == template_id,
                    SopExecution.session_id == (session_id or ""),
                    SopExecution.status == "pending",
                )
            ).scalars().first()
            if existing:
                return None
            created = 0
            for index, step in enumerate(steps, start=1):
                due_hours = int(step.get("due_hours") or 24)
                session.add(SopExecution(
                    template_id=template_id,
                    session_id=session_id or "",
                    customer_id=customer_id,
                    lead_id=lead_id,
                    stage=template.stage or "",
                    step_index=index,
                    step_name=step.get("name") or f"步骤 {index}",
                    due_hours=due_hours,
                    due_at=_datetime_plus_hours(due_hours),
                    status="pending",
                ))
                created += 1
            return {"template_id": template_id, "created": created}

    def complete_step(self, execution_id: int) -> dict | None:
        with session_scope() as session:
            obj = session.get(SopExecution, execution_id)
            if not obj:
                return None
            obj.status = "done"
            obj.done_at = _now()
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def skip_step(self, execution_id: int) -> dict | None:
        with session_scope() as session:
            obj = session.get(SopExecution, execution_id)
            if not obj:
                return None
            obj.status = "skipped"
            obj.done_at = _now()
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def list_executions(self, status: str = "", stage: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(SopExecution).order_by(SopExecution.id.desc())
            if status:
                query = query.where(SopExecution.status == status)
            if stage:
                query = query.where(SopExecution.stage == stage)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def on_stage_change(self, customer_id: int, stage: str, session_id: str = "") -> int:
        """客户阶段变化时自动下发匹配阶段的 SOP"""
        try:
            if not stage:
                return 0
            if not session_id and customer_id:
                try:
                    from core.sales_crm import crm
                    customer = crm.get(customer_id)
                    session_id = (customer or {}).get("session_id") or ""
                except Exception as e:
                    logger.debug("SopManager.on_stage_change 异常已忽略: %s", e)
            templates = self.list_templates(stage=stage, active_only=True)
            created_total = 0
            for template in templates:
                result = self.start_execution(
                    template["id"],
                    session_id=session_id,
                    customer_id=customer_id,
                )
                if result:
                    created_total += result.get("created", 0)
            if created_total:
                logger.info("客户 %s 进入 %s，自动下发 %s 个SOP步骤", customer_id, stage, created_total)
        except Exception as e:
            logger.error(f"SOP阶段联动失败: {e}")
            return 0

        # 销售流程工作流：阶段变化事件
        try:
            from core.sales_flow import sales_flow
            sales_flow.trigger_event("customer.stage_changed", {
                "customer_id": customer_id, "session_id": session_id, "stage": stage,
            })
        except Exception as e:
            logger.error("销售流程阶段事件触发失败: %s", e)
        return created_total

    def refresh_overdue(self) -> dict:
        now = _now()
        with session_scope() as session:
            rows = session.execute(
                select(SopExecution).where(
                    SopExecution.status == "pending",
                    SopExecution.due_at != "",
                    SopExecution.due_at < now,
                )
            ).scalars().all()
            for obj in rows:
                obj.status = "overdue"
                obj.updated_at = _now()
            return {"overdue": len(rows)}

    def stats(self) -> dict:
        executions = self.list_executions(limit=100000)
        total = len(executions)
        by_status = {}
        for e in executions:
            status = e.get("status") or "pending"
            by_status[status] = by_status.get(status, 0) + 1
        done = by_status.get("done", 0)
        by_template = {}
        for e in executions:
            tid = e.get("template_id")
            bucket = by_template.setdefault(tid, {"total": 0, "done": 0})
            bucket["total"] += 1
            if e.get("status") == "done":
                bucket["done"] += 1
        templates = self.list_templates()
        template_stats = []
        for t in templates:
            bucket = by_template.get(t["id"], {"total": 0, "done": 0})
            template_stats.append({
                "template_id": t["id"],
                "name": t["name"],
                "stage": t["stage"],
                "total": bucket["total"],
                "done": bucket["done"],
                "completion_rate": round(bucket["done"] / bucket["total"] * 100, 1) if bucket["total"] else 0.0,
            })
        return {
            "total": total,
            "done": done,
            "pending": by_status.get("pending", 0),
            "overdue": by_status.get("overdue", 0),
            "completion_rate": round(done / total * 100, 1) if total else 0.0,
            "by_status": by_status,
            "by_template": template_stats,
        }

    @staticmethod
    def _template_dict(obj) -> dict:
        result = _row_to_dict(obj)
        try:
            result["steps"] = json.loads(result.get("steps_json") or "[]")
        except (TypeError, ValueError):
            result["steps"] = []
        return result


sop_manager = SopManager()
