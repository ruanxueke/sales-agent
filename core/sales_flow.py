"""销售流程企业级框架：可配置工作流、预测管道、智能派单。

- 工作流：触发器 + 节点（条件/设字段/建跟进/通知/转人工/发消息/延迟），记录执行日志；
- 预测：基于阶段、意向分、预算、交互热度、跟进状态的赢单概率与流失风险，输出管道预期；
- 派单：轮询 / 负载均衡 / 按能力加权，支持规则管理与手动改派。
"""
from __future__ import annotations
import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import func, select, text

from config.settings import settings
from core.db import init_db, session_scope
from core.models import (
    Customer,
    DispatchRule,
    FollowupTask,
    HandoverRequest,
    Lead,
    Notification,
    Order,
    SalesWorkflow,
    SalesWorkflowExecution,
    TeamMember,
)

logger = logging.getLogger(__name__)

TRIGGERS = ["manual", "customer.created", "customer.stage_changed", "order.paid", "lead.assigned", "followup.overdue"]
NODE_TYPES = ["condition", "set_field", "create_followup", "notify", "handover", "send_message", "delay"]
DISPATCH_STRATEGIES = ["round_robin", "load_balanced", "weighted"]
DEFAULT_DEAL_VALUE = 198


def _deal_value(obj: dict, order_map: dict, stage: str) -> float:
    """取关联已支付订单金额；已成交但无订单记录时使用默认客单价。"""
    amount = float(order_map.get(str(obj.get("id"))) or 0)
    session_key = "session:" + str(obj.get("session_id") or "")
    amount = max(amount, float(order_map.get(session_key) or 0))
    if not amount and stage in ("won", "enrolled"):
        return float(DEFAULT_DEAL_VALUE)
    return amount

DEFAULT_WORKFLOWS = [
    {
        "name": "付款成功交付",
        "trigger": "order.paid",
        "nodes": [
            {"type": "set_field", "field": "stage", "value": "won", "label": "更新成交阶段"},
            {"type": "create_followup", "hours": 24, "content": "回访学员学习体验，确认交付完成", "label": "24小时后回访"},
            {"type": "notify", "receivers": "叙白", "content": "新订单已支付，请确认交付", "label": "通知交付人"},
        ],
    },
    {
        "name": "高意向线索通知",
        "trigger": "customer.stage_changed",
        "nodes": [
            {"type": "condition", "field": "stage", "op": "in", "value": ["high_intent", "enrolled"], "label": "判断高意向"},
            {"type": "notify", "receivers": "销售主管", "content": "客户进入高意向阶段，请及时跟进", "label": "通知主管"},
        ],
    },
    {
        "name": "跟进超时提醒",
        "trigger": "followup.overdue",
        "nodes": [
            {"type": "condition", "field": "status", "op": "eq", "value": "pending", "label": "判断跟进未完成"},
            {"type": "notify", "receivers": "负责人", "content": "跟进任务已超时，请尽快处理", "label": "超时提醒"},
            {"type": "handover", "reason": "跟进超时，转主管处理", "label": "转主管"},
        ],
    },
    {
        "name": "新线索自动分配",
        "trigger": "lead.assigned",
        "nodes": [
            {"type": "create_followup", "hours": 1, "content": "新线索首触跟进", "label": "1小时内首触"},
            {"type": "notify", "receivers": "销售主管", "content": "新线索已分配，请关注首触", "label": "通知主管"},
        ],
    },
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _parse_nodes(nodes) -> list[dict]:
    if isinstance(nodes, list):
        return nodes
    if isinstance(nodes, str):
        try:
            return json.loads(nodes or "[]")
        except (TypeError, ValueError):
            return []
    return []


def _parse_json(value, default):
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return default


class SalesFlowManager:
    def __init__(self):
        # 不在 __init__ 里碰数据库。原来模块导入期就会 SELECT sales_workflows 并按
        # 需写入默认工作流，于是"导入本模块"变成"必须有一张已建好且可写的表"，
        # 表缺失时导入期直接失败、报错还看不出是哪张表。改成首次使用时惰性初始化。
        self._ready = False
        self._ready_lock = threading.Lock()

    @contextmanager
    def _db(self):
        """业务方法统一从这里取会话，顺带保证首次调用前已完成初始化与种子写入。"""
        self._ensure_ready()
        with session_scope() as session:
            yield session

    def _ensure_ready(self) -> None:
        if self._ready:
            return
        with self._ready_lock:
            if self._ready:
                return
            try:
                init_db()
                self._seed_defaults()
            except Exception as e:
                logger.warning("销售流程初始化失败（表缺失或数据库不可用），下次调用会重试: %s", e)
                raise
            self._ready = True

    def _seed_defaults(self):
        """首次启动写入内置工作流，保证默认模板可运行、可自动触发。

        必须直接用 session_scope：走 self._db() 会自锁。
        """
        with session_scope() as session:
            count = session.execute(
                select(func.count()).select_from(SalesWorkflow).where(SalesWorkflow.tenant_id == 0)
            ).scalar() or 0
            if count:
                return
            for item in DEFAULT_WORKFLOWS:
                session.add(SalesWorkflow(
                    tenant_id=0,
                    name=item["name"],
                    trigger=item["trigger"],
                    enabled=True,
                    nodes_json=json.dumps(item["nodes"], ensure_ascii=False),
                ))

    # ============================================================
    # 工作流模板
    # ============================================================

    def list_workflows(self, tenant_id: int | None = None) -> list[dict]:
        with self._db() as session:
            query = select(SalesWorkflow).order_by(SalesWorkflow.id.desc())
            if tenant_id is not None:
                query = query.where(SalesWorkflow.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
            items = []
            for r in rows:
                d = _row_to_dict(r)
                d["nodes"] = _parse_nodes(d.pop("nodes_json", "[]"))
                items.append(d)
            return items

    def create_workflow(self, tenant_id: int | None, name: str, trigger: str, nodes: list[dict], enabled: bool = True) -> dict:
        trigger = trigger if trigger in TRIGGERS else "manual"
        with self._db() as session:
            obj = SalesWorkflow(
                tenant_id=tenant_id or 0,
                name=(name or "").strip() or "未命名工作流",
                trigger=trigger,
                enabled=bool(enabled),
                nodes_json=json.dumps(nodes or [], ensure_ascii=False),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_workflow(self, workflow_id: int, tenant_id: int | None = None, **fields) -> dict | None:
        allowed = {"name", "trigger", "nodes", "enabled"}
        with self._db() as session:
            query = select(SalesWorkflow).where(SalesWorkflow.id == workflow_id)
            if tenant_id is not None:
                query = query.where(SalesWorkflow.tenant_id == tenant_id)
            obj = session.execute(query).scalars().first()
            if not obj:
                return None
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "nodes":
                    obj.nodes_json = json.dumps(value or [], ensure_ascii=False)
                elif key == "trigger":
                    obj.trigger = value if value in TRIGGERS else obj.trigger
                else:
                    setattr(obj, key, value)
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def delete_workflow(self, workflow_id: int, tenant_id: int | None = None) -> bool:
        with self._db() as session:
            query = select(SalesWorkflow).where(SalesWorkflow.id == workflow_id)
            if tenant_id is not None:
                query = query.where(SalesWorkflow.tenant_id == tenant_id)
            obj = session.execute(query).scalars().first()
            if not obj:
                return False
            session.delete(obj)
            return True

    # ============================================================
    # 工作流执行
    # ============================================================

    def run_workflow(self, workflow_id: int, context: dict | None = None, tenant_id: int | None = None) -> dict:
        context = context or {}
        with self._db() as session:
            query = select(SalesWorkflow).where(SalesWorkflow.id == workflow_id)
            if tenant_id is not None:
                query = query.where(SalesWorkflow.tenant_id == tenant_id)
            workflow = session.execute(query).scalars().first()
            if not workflow:
                return {"ok": False, "error": "工作流不存在或无权访问"}
            nodes = _parse_nodes(workflow.nodes_json)
            execution = SalesWorkflowExecution(
                workflow_id=workflow_id,
                tenant_id=workflow.tenant_id,
                context_json=json.dumps(context, ensure_ascii=False),
                status="running",
                started_at=_now(),
            )
            session.add(execution)
            session.flush()
            execution_id = execution.id

            merged = self._merge_context(session, context)
            node_results = []
            failed = False
            for index, node in enumerate(nodes, start=1):
                result = self._run_node(session, node, merged, context)
                node_results.append({"index": index, **result})
                if result.get("skipped"):
                    break
                if not result.get("ok"):
                    failed = True

            execution.status = "failed" if failed else "done"
            execution.finished_at = _now()
            execution.result_json = json.dumps({
                "nodes": node_results,
                "context": {k: v for k, v in context.items() if k not in ("customer", "lead", "order")},
            }, ensure_ascii=False)
            session.flush()
            return {
                "ok": not failed,
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "name": workflow.name,
                "node_results": node_results,
            }

    def trigger_event(self, event: str, context: dict | None = None, tenant_id: int | None = None) -> list[dict]:
        """业务事件触发：匹配已启用工作流并执行。"""
        context = context or {}
        results = []
        with self._db() as session:
            query = select(SalesWorkflow).where(
                SalesWorkflow.trigger == event,
                SalesWorkflow.enabled.is_(True),
            )
            if tenant_id is not None:
                query = query.where(SalesWorkflow.tenant_id == tenant_id)
            else:
                query = query.where(SalesWorkflow.tenant_id == 0)
            rows = session.execute(query).scalars().all()
        for workflow in rows:
            try:
                results.append(self.run_workflow(workflow.id, context, tenant_id))
            except Exception as e:
                logger.error("工作流 %s 触发失败: %s", workflow.id, e)
                results.append({"ok": False, "workflow_id": workflow.id, "error": str(e)[:200]})
        return results

    def list_executions(self, tenant_id: int | None = None, limit: int = 100) -> list[dict]:
        with self._db() as session:
            query = select(SalesWorkflowExecution).order_by(SalesWorkflowExecution.id.desc()).limit(limit)
            if tenant_id is not None:
                query = query.where(SalesWorkflowExecution.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
            items = []
            for r in rows:
                d = _row_to_dict(r)
                d["result"] = _parse_json(d.pop("result_json", "{}"), {})
                d["context"] = _parse_json(d.pop("context_json", "{}"), {})
                items.append(d)
            return items

    def workflow_stats(self, tenant_id: int | None = None) -> dict:
        workflows = self.list_workflows(tenant_id)
        executions = self.list_executions(tenant_id, limit=1000)
        return {
            "workflows": len(workflows),
            "enabled": sum(1 for w in workflows if w.get("enabled")),
            "executions": len(executions),
            "done": sum(1 for e in executions if e.get("status") == "done"),
            "failed": sum(1 for e in executions if e.get("status") == "failed"),
        }

    @staticmethod
    def _merge_context(session, context: dict) -> dict:
        merged = {k: v for k, v in context.items() if not isinstance(v, dict)}
        customer_id = context.get("customer_id")
        if customer_id:
            obj = session.get(Customer, int(customer_id))
            if obj:
                merged.update(_row_to_dict(obj))
        lead_id = context.get("lead_id")
        if lead_id:
            obj = session.get(Lead, int(lead_id))
            if obj:
                merged.update(_row_to_dict(obj))
        order = context.get("order")
        if isinstance(order, dict):
            merged.update({f"order_{k}": v for k, v in order.items()})
        return merged

    def _run_node(self, session, node: dict, merged: dict, context: dict) -> dict:
        node_type = node.get("type")
        label = node.get("label") or node_type
        try:
            if node_type == "condition":
                return self._node_condition(node, merged)
            if node_type == "set_field":
                return self._node_set_field(session, node, context)
            if node_type == "create_followup":
                return self._node_create_followup(session, node, context)
            if node_type == "notify":
                return self._node_notify(session, node, merged, context)
            if node_type == "handover":
                return self._node_handover(session, node, context)
            if node_type == "send_message":
                return self._node_send_message(session, node, merged, context)
            if node_type == "delay":
                return {"ok": True, "type": node_type, "label": label, "note": f"延迟 {node.get('hours', 0)} 小时（由调度器执行）"}
            return {"ok": False, "type": node_type, "label": label, "error": f"不支持的节点类型: {node_type}"}
        except Exception as e:
            logger.error("工作流节点 %s 执行失败: %s", label, e)
            return {"ok": False, "type": node_type, "label": label, "error": str(e)[:200]}

    @staticmethod
    def _node_condition(node: dict, merged: dict) -> dict:
        field = node.get("field")
        op = node.get("op") or "eq"
        value = node.get("value")
        actual = merged.get(field)
        matched = False
        if op == "eq":
            matched = str(actual) == str(value)
        elif op == "neq":
            matched = str(actual) != str(value)
        elif op == "contains":
            matched = str(value) in str(actual or "")
        elif op == "in":
            matched = str(actual) in [str(x) for x in (value or [])]
        elif op == "gt":
            try:
                matched = float(actual or 0) > float(value or 0)
            except Exception:
                matched = False
        elif op == "lt":
            try:
                matched = float(actual or 0) < float(value or 0)
            except Exception:
                matched = False
        if not matched:
            return {"ok": True, "type": "condition", "label": node.get("label") or "条件", "skipped": True, "note": "条件不满足，跳过后续节点"}
        return {"ok": True, "type": "condition", "label": node.get("label") or "条件", "matched": True}

    @staticmethod
    def _node_set_field(session, node: dict, context: dict) -> dict:
        field = node.get("field")
        value = node.get("value")
        if field == "stage" and context.get("customer_id"):
            from core.sales_crm import crm
            crm.advance_stage(int(context["customer_id"]), str(value), trigger="工作流")
            return {"ok": True, "type": "set_field", "label": node.get("label") or "更新阶段", "field": field, "value": value}
        if field and context.get("lead_id"):
            from core.lead import lead_manager
            lead_manager.update(int(context["lead_id"]), **{field: value})
            return {"ok": True, "type": "set_field", "label": node.get("label") or "更新字段", "field": field, "value": value}
        return {"ok": True, "type": "set_field", "label": node.get("label") or "更新字段", "note": "缺少 customer_id/lead_id，仅记录"}

    @staticmethod
    def _node_create_followup(session, node: dict, context: dict) -> dict:
        hours = int(node.get("hours") or 24)
        due = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        session.add(FollowupTask(
            session_id=context.get("session_id") or "",
            lead_id=context.get("lead_id"),
            customer_id=context.get("customer_id"),
            node=1,
            node_label=f"工作流-{hours}h",
            due_at=due,
            status="pending",
            channel=context.get("source") or "official",
            content=node.get("content") or "",
        ))
        return {"ok": True, "type": "create_followup", "label": node.get("label") or "创建跟进", "due_at": due}

    @staticmethod
    def _node_notify(session, node: dict, merged: dict, context: dict) -> dict:
        content = node.get("content") or "销售流程通知"
        session.add(Notification(
            customer_id=int(context.get("customer_id") or 0),
            target=node.get("receivers") or merged.get("owner") or "",
            content=content,
            status="pending",
        ))
        return {"ok": True, "type": "notify", "label": node.get("label") or "通知", "receivers": node.get("receivers") or "-"}

    @staticmethod
    def _node_handover(session, node: dict, context: dict) -> dict:
        session.add(HandoverRequest(
            session_id=context.get("session_id") or "",
            customer_id=context.get("customer_id"),
            lead_id=context.get("lead_id"),
            source=context.get("source") or "wechat",
            reason=node.get("reason") or "工作流触发转人工",
            status="requested",
        ))
        return {"ok": True, "type": "handover", "label": node.get("label") or "转人工", "reason": node.get("reason") or "-"}

    @staticmethod
    def _node_send_message(session, node: dict, merged: dict, context: dict) -> dict:
        content = node.get("content") or ""
        session.add(Notification(
            customer_id=int(context.get("customer_id") or 0),
            target=merged.get("session_id") or context.get("session_id") or "",
            content=content,
            status="pending",
        ))
        return {
            "ok": True,
            "type": "send_message",
            "label": node.get("label") or "发送消息",
            "channel": node.get("channel") or "wechat",
            "note": "已落通知，等待通道发送",
        }

    # ============================================================
    # 预测管道
    # ============================================================

    def predictions(self, tenant_id: int | None = None, limit: int = 50) -> dict:
        from core.sales_crm import crm

        try:
            customers = crm.list_customers()
        except Exception:
            customers = []
        with self._db() as session:
            query = select(Lead).order_by(Lead.updated_at.desc())
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == tenant_id)
            try:
                leads = [_row_to_dict(r) for r in session.execute(query).scalars().all()]
            except Exception:
                raw_sql = "SELECT * FROM leads"
                raw_params = {}
                if tenant_id is not None:
                    raw_sql += " WHERE tenant_id=:tid"
                    raw_params["tid"] = tenant_id
                raw_sql += " ORDER BY updated_at DESC"
                try:
                    leads = [dict(r) for r in session.execute(text(raw_sql), raw_params).mappings().all()]
                except Exception:
                    leads = []
            order_query = select(Order).where(Order.status.in_(["paid", "completed", "won", "delivered"]))
            if tenant_id is not None:
                order_query = order_query.where(Order.tenant_id == tenant_id)
            try:
                orders = [_row_to_dict(r) for r in session.execute(order_query).scalars().all()]
            except Exception:
                raw_sql = "SELECT * FROM orders"
                raw_params = {}
                if tenant_id is not None:
                    raw_sql += " WHERE tenant_id=:tid"
                    raw_params["tid"] = tenant_id
                raw_sql += " ORDER BY updated_at DESC"
                try:
                    orders = [dict(r) for r in session.execute(text(raw_sql), raw_params).mappings().all()]
                except Exception:
                    orders = []
            chat_counts = {}
            try:
                from sqlalchemy import text
                rows = session.execute(text("SELECT session_id, COUNT(*) AS n FROM customer_chat_log GROUP BY session_id")).mappings().all()
                chat_counts = {r["session_id"]: int(r["n"]) for r in rows}
            except Exception:
                chat_counts = {}

        items = []
        order_map = {}
        for o in orders:
            amount = float(o.get("amount") or 0)
            for key in (o.get("customer_id"), o.get("lead_id")):
                if key:
                    order_map[str(key)] = max(order_map.get(str(key), 0), amount)
            if o.get("session_id"):
                order_map["session:" + str(o.get("session_id"))] = max(order_map.get("session:" + str(o.get("session_id")), 0), amount)
        for c in customers:
            p = self._predict_customer(c, chat_counts, order_map)
            if p:
                items.append(p)
        for lead in leads[:200]:
            p = self._predict_lead(lead, chat_counts, order_map)
            if p:
                items.append(p)

        items.sort(key=lambda x: x.get("expected_value", 0), reverse=True)
        items = items[:limit]
        total_expected = round(sum(x.get("expected_value", 0) for x in items), 2)
        high_prob = sum(1 for x in items if x.get("win_probability", 0) >= 0.6)
        high_churn = sum(1 for x in items if x.get("churn_risk", 0) >= 0.6)
        return {
            "total": len(items),
            "total_expected": total_expected,
            "high_probability": high_prob,
            "high_churn_risk": high_churn,
            "items": items,
        }

    @staticmethod
    def _predict_customer(customer: dict, chat_counts: dict, order_map: dict) -> dict | None:
        stage = customer.get("stage") or "new"
        weights = {
            "new": 0.05, "understanding": 0.15, "recommended": 0.3,
            "high_intent": 0.65, "enrolled": 0.85, "won": 1.0, "lost": 0.02,
        }
        score = weights.get(stage, 0.05) * 0.5
        intent = int(customer.get("intent_score") or 0)
        score += min(1.0, intent / 100) * 0.3
        budget = (customer.get("budget") or "")
        if budget and budget not in ("", "未知"):
            score += 0.1
        chat = int(chat_counts.get(customer.get("session_id") or "", 0))
        score += min(0.1, chat / 20)
        win = round(min(0.99, max(0.01, score)), 3)

        risk = 0.2
        if stage in ("new", "understanding"):
            risk += 0.25
        if stage in ("lost", "rejected"):
            risk += 0.45
        if chat == 0:
            risk += 0.2
        churn = round(min(0.95, risk), 3)
        return {
            "kind": "customer",
            "id": customer.get("id"),
            "nickname": customer.get("nickname") or customer.get("display_id") or "",
            "session_id": customer.get("session_id") or "",
            "stage": stage,
            "owner": "",
            "source": customer.get("source") or "",
            "win_probability": win,
            "churn_risk": churn,
            "next_follow_up": customer.get("next_follow_up") or "",
            "expected_value": round(win * _deal_value(customer, order_map, stage), 2),
        }

    @staticmethod
    def _predict_lead(lead: dict, chat_counts: dict, order_map: dict) -> dict | None:
        stage = lead.get("stage") or "new"
        weights = {
            "new": 0.05, "understanding": 0.15, "recommended": 0.3,
            "high_intent": 0.65, "enrolled": 0.85, "won": 1.0, "lost": 0.02,
        }
        score = weights.get(stage, 0.05) * 0.5
        intent = int(lead.get("intent_score") or 0)
        score += min(1.0, intent / 100) * 0.3
        if (lead.get("budget") or "") not in ("", "未知"):
            score += 0.1
        chat = int(chat_counts.get(lead.get("session_id") or "", 0))
        score += min(0.1, chat / 20)
        win = round(min(0.99, max(0.01, score)), 3)
        risk = 0.2
        if stage in ("new", "understanding"):
            risk += 0.25
        if stage in ("lost", "rejected"):
            risk += 0.45
        if chat == 0:
            risk += 0.2
        churn = round(min(0.95, risk), 3)
        return {
            "kind": "lead",
            "id": lead.get("id"),
            "nickname": lead.get("nickname") or lead.get("name") or lead.get("display_id") or "",
            "session_id": lead.get("session_id") or "",
            "stage": stage,
            "owner": lead.get("owner") or "",
            "source": lead.get("source") or "",
            "win_probability": win,
            "churn_risk": churn,
            "next_follow_up": lead.get("next_follow_up") or "",
            "expected_value": round(win * _deal_value(lead, order_map, stage), 2),
        }

    # ============================================================
    # 智能派单
    # ============================================================

    def list_dispatch_rules(self, tenant_id: int | None = None) -> list[dict]:
        with self._db() as session:
            query = select(DispatchRule).order_by(DispatchRule.id.desc())
            if tenant_id is not None:
                query = query.where(DispatchRule.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
            items = []
            for r in rows:
                d = _row_to_dict(r)
                d["params"] = _parse_json(d.pop("params_json", "{}"), {})
                items.append(d)
            if tenant_id is None and not items:
                items = [{
                    "id": 0, "tenant_id": 0, "name": "默认轮询派单", "strategy": "round_robin",
                    "enabled": True, "params": {}, "builtin": True,
                }]
            return items

    def create_dispatch_rule(self, tenant_id: int | None, name: str, strategy: str, params: dict | None = None, enabled: bool = True) -> dict:
        strategy = strategy if strategy in DISPATCH_STRATEGIES else "round_robin"
        with self._db() as session:
            obj = DispatchRule(
                tenant_id=tenant_id or 0,
                name=(name or "").strip() or "未命名派单规则",
                strategy=strategy,
                enabled=bool(enabled),
                params_json=json.dumps(params or {}, ensure_ascii=False),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def delete_dispatch_rule(self, rule_id: int, tenant_id: int | None = None) -> bool:
        with self._db() as session:
            query = select(DispatchRule).where(DispatchRule.id == rule_id)
            if tenant_id is not None:
                query = query.where(DispatchRule.tenant_id == tenant_id)
            obj = session.execute(query).scalars().first()
            if not obj:
                return False
            session.delete(obj)
            return True

    def dispatch_candidates(self, tenant_id: int | None = None) -> list[dict]:
        with self._db() as session:
            members = session.execute(select(TeamMember)).scalars().all()
            query = select(Lead)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == tenant_id)
            try:
                leads = [_row_to_dict(r) for r in session.execute(query).scalars().all()]
            except Exception:
                raw_sql = "SELECT * FROM leads"
                raw_params = {}
                if tenant_id is not None:
                    raw_sql += " WHERE tenant_id=:tid"
                    raw_params["tid"] = tenant_id
                try:
                    leads = [dict(r) for r in session.execute(text(raw_sql), raw_params).mappings().all()]
                except Exception:
                    leads = []

        owner_load = {}
        owner_won = {}
        for lead in leads:
            owner = (lead.get("owner") or "").strip()
            if not owner:
                continue
            owner_load[owner] = owner_load.get(owner, 0) + 1
            if lead.get("stage") in ("won", "enrolled"):
                owner_won[owner] = owner_won.get(owner, 0) + 1

        names = set(owner_load.keys())
        for m in members:
            name = (m.name or m.nickname or "").strip()
            if name:
                names.add(name)

        items = []
        for name in sorted(names):
            items.append({
                "owner": name,
                "load": owner_load.get(name, 0),
                "won": owner_won.get(name, 0),
            })
        items.sort(key=lambda x: (x["load"], -x["won"]))
        return items

    def dispatch_lead(self, lead_id: int, tenant_id: int | None = None, strategy: str = "") -> dict:
        from core.lead import lead_manager

        rules = self.list_dispatch_rules(tenant_id)
        rule = next((r for r in rules if r.get("enabled")), None)
        strategy = strategy or (rule or {}).get("strategy") or "round_robin"
        candidates = self.dispatch_candidates(tenant_id)
        if not candidates:
            owner = settings.LEAD_DEFAULT_OWNER
        elif strategy == "load_balanced":
            owner = min(candidates, key=lambda x: x["load"])["owner"]
        elif strategy == "weighted":
            owner = max(candidates, key=lambda x: x["won"])["owner"]
        else:
            with self._db() as session:
                query = select(Lead).order_by(Lead.assigned_at.desc())
                if tenant_id is not None:
                    query = query.where(Lead.tenant_id == tenant_id)
                last = session.execute(query).scalars().first()
            owners = [c["owner"] for c in candidates]
            if not owners:
                owner = settings.LEAD_DEFAULT_OWNER
            elif last and (last.owner or "") in owners:
                idx = owners.index(last.owner)
                owner = owners[(idx + 1) % len(owners)]
            else:
                owner = owners[0]
        lead = lead_manager.assign(lead_id, owner)
        if not lead:
            return {"ok": False, "error": "线索不存在"}
        return {"ok": True, "lead_id": lead_id, "owner": owner, "strategy": strategy, "lead": lead}

    def dispatch_stats(self, tenant_id: int | None = None) -> dict:
        with self._db() as session:
            query = select(Lead)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == tenant_id)
            try:
                leads = [_row_to_dict(r) for r in session.execute(query).scalars().all()]
            except Exception:
                raw_sql = "SELECT * FROM leads"
                raw_params = {}
                if tenant_id is not None:
                    raw_sql += " WHERE tenant_id=:tid"
                    raw_params["tid"] = tenant_id
                try:
                    leads = [dict(r) for r in session.execute(text(raw_sql), raw_params).mappings().all()]
                except Exception:
                    leads = []
        by_owner = {}
        unassigned = 0
        for lead in leads:
            owner = (lead.get("owner") or "").strip()
            if not owner:
                unassigned += 1
                continue
            by_owner[owner] = by_owner.get(owner, 0) + 1
        return {
            "total": len(leads),
            "unassigned": unassigned,
            "assigned": len(leads) - unassigned,
            "by_owner": by_owner,
            "rules": len(self.list_dispatch_rules(tenant_id)),
        }


sales_flow = SalesFlowManager()
