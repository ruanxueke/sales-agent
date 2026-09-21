"""多 Agent 编排框架：规划器 + 执行器 + 验证器（可插拔任务，默认单 Agent 直通）"""
from __future__ import annotations
import logging
import time
import uuid

from config.settings import settings

logger = logging.getLogger(__name__)


class AgentTask:
    def __init__(self, name: str, handler=None, requires: list[str] | None = None):
        self.name = name
        self.handler = handler
        self.requires = requires or []


class Planner:
    """根据客户问题拆解为任务序列"""

    def plan(self, message: str, customer: dict | None = None) -> list[dict]:
        tasks = []
        # 简单规则：涉及订单/物流/支付时拆出工具任务；其余走销售对话主任务
        if any(w in message for w in ("订单", "物流", "发货", "发票", "付款", "价格", "优惠")):
            tasks.append({"name": "intent_extract", "description": "提取订单/意向信息"})
            if any(w in message for w in ("订单", "物流", "发货", "发票")):
                tasks.append({"name": "tool_query", "description": "查询订单/物流"})
        tasks.append({"name": "sales_reply", "description": "生成销售回复"})
        return tasks


class Executor:
    def __init__(self):
        self._handlers = {}

    def register(self, name: str, handler):
        self._handlers[name] = handler

    def run(self, task: dict, context: dict) -> dict:
        name = task.get("name")
        handler = self._handlers.get(name)
        if not handler:
            return {"ok": False, "task": name, "result": "", "error": f"未注册执行器: {name}"}
        try:
            result = handler(context)
            return {"ok": True, "task": name, "result": result}
        except Exception as e:
            logger.warning("执行器 %s 失败: %s", name, e)
            return {"ok": False, "task": name, "result": "", "error": str(e)}


class Validator:
    """校验执行结果是否完整、是否包含明确下一步"""

    def validate(self, outputs: list[dict], message: str) -> dict:
        sales = next((o for o in outputs if o.get("task") == "sales_reply"), None)
        if not sales or not sales.get("result"):
            return {"ok": False, "reason": "销售回复缺失"}
        reply = str(sales["result"])
        if len(reply) < 4:
            return {"ok": False, "reason": "回复过短"}
        return {"ok": True, "reason": "校验通过"}


class AgentOrchestrator:
    def __init__(self):
        self.planner = Planner()
        self.executor = Executor()
        self.validator = Validator()
        self.enabled = settings.AGENT_ORCHESTRATOR_ENABLED

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "mode": "multi-agent" if self.enabled else "single-agent",
            "registered_tasks": sorted(self.executor._handlers.keys()),
        }

    def run(self, message: str, customer: dict | None = None, sales_fn=None) -> dict:
        trace_id = uuid.uuid4().hex[:12]
        start = time.time()
        if not self.enabled:
            return {"trace_id": trace_id, "ok": True, "mode": "single-agent", "outputs": [], "elapsed_ms": 0}
        plan = self.planner.plan(message, customer)
        context = {"message": message, "customer": customer or {}, "sales_fn": sales_fn}
        outputs = []
        for task in plan:
            outputs.append(self.executor.run(task, context))
        result = self.validator.validate(outputs, message)
        return {
            "trace_id": trace_id,
            "ok": result["ok"],
            "reason": result["reason"],
            "mode": "multi-agent",
            "plan": plan,
            "outputs": outputs,
            "elapsed_ms": round((time.time() - start) * 1000, 1),
        }


orchestrator = AgentOrchestrator()
