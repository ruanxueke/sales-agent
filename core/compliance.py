"""合规与人工层：转人工规则、停止触达、审计"""
from __future__ import annotations
import logging
import threading
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import ComplianceRule
from core.tenant_context import tenant_scope

logger = logging.getLogger(__name__)

DEFAULT_RULES = [
    ("handover", "真人|人工|投诉|退款|退费|法律|律师|未成年|未成年人|孩子|学生|报警|315", "handover", 90, "强制转人工"),
    ("stop", "不买了|不要了|不需要|别烦我|不用了|不考虑|不感兴趣|别再联系|拉黑", "stop", 80, "明确拒绝停止触达"),
    ("handover", "金额|大额|保证|承诺|稳赚|包赚|百分之百|一定有效", "handover", 50, "大额或高风险承诺"),
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class ComplianceManager:
    def __init__(self):
        # 不在 __init__ 里碰数据库：原来"导入 core.compliance"就等于"必须有一张
        # 已建好的 compliance_rules 表"，表缺失时导入期直接抛异常，整个进程起不来
        # 而且报错看不出是哪张表。改成首次使用时惰性初始化。
        self._ready = False
        self._seeded_tenants = set()
        self._ready_lock = threading.Lock()

    @contextmanager
    def _db(self, tenant_id: int | None = None):
        """业务方法统一从这里取会话，顺带保证首次调用前已完成初始化与种子写入。"""
        self._ensure_ready(tenant_id)
        with tenant_scope(tenant_id):
            with session_scope() as session:
                yield session

    def _ensure_ready(self, tenant_id: int | None = None) -> None:
        if self._ready:
            return
        with self._ready_lock:
            if self._ready:
                return
            try:
                init_db()
                self._ready = True
            except Exception as e:
                logger.warning("合规规则初始化失败（表缺失或数据库不可用），下次调用会重试: %s", e)
                raise
        self._seed(tenant_id)

    def _seed(self, tenant_id: int | None = None) -> None:
        tenant_key = int(tenant_id or 0)
        if tenant_key in self._seeded_tenants:
            return
        # 必须直接用 session_scope：走 self._db() 会自锁。
        with tenant_scope(tenant_id):
            with session_scope() as session:
                rows = session.execute(select(ComplianceRule)).scalars().all()
                if rows:
                    self._seeded_tenants.add(tenant_key)
                    return
                for rule_type, trigger_words, action, priority, description in DEFAULT_RULES:
                    session.add(ComplianceRule(
                        tenant_id=tenant_key,
                        rule_type=rule_type,
                        trigger_words=trigger_words,
                        action=action,
                        priority=priority,
                        enabled=True,
                        description=description,
                    ))
        self._seeded_tenants.add(tenant_key)

    def list_rules(
        self,
        rule_type: str = "",
        enabled_only: bool = False,
        tenant_id: int | None = None,
    ) -> list[dict]:
        with self._db(tenant_id) as session:
            query = select(ComplianceRule).order_by(ComplianceRule.priority.desc(), ComplianceRule.id)
            if rule_type:
                query = query.where(ComplianceRule.rule_type == rule_type)
            if enabled_only:
                query = query.where(ComplianceRule.enabled.is_(True))
            return [_row_to_dict(r) for r in session.execute(query).scalars().all()]

    def create_rule(
        self,
        rule_type: str,
        trigger_words: str,
        action: str = "handover",
        priority: int = 0,
        description: str = "",
        tenant_id: int | None = None,
    ) -> dict:
        with self._db(tenant_id) as session:
            obj = ComplianceRule(
                rule_type=rule_type or "handover",
                trigger_words=trigger_words or "",
                action=action if action in ("handover", "stop", "notify") else "handover",
                priority=int(priority or 0),
                enabled=True,
                description=description or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_rule(
        self,
        rule_id: int,
        tenant_id: int | None = None,
        **fields,
    ) -> dict | None:
        allowed = {"rule_type", "trigger_words", "action", "priority", "enabled", "description"}
        with self._db(tenant_id) as session:
            obj = session.get(ComplianceRule, rule_id)
            if not obj:
                return None
            for k, v in fields.items():
                if k in allowed and v is not None:
                    setattr(obj, k, v)
            return _row_to_dict(obj)

    def check(self, message: str, tenant_id: int | None = None) -> dict:
        """返回最高优先级命中的规则动作；无命中返回 None"""
        message = message or ""
        best = None
        for rule in self.list_rules(enabled_only=True, tenant_id=tenant_id):
            words = [w for w in (rule.get("trigger_words") or "").split("|") if w]
            if any(w in message for w in words):
                best = rule
                break
        if best:
            return {"action": best.get("action"), "rule_id": best.get("id"), "rule_type": best.get("rule_type"), "description": best.get("description")}
        return {"action": None}

    def stats(self, tenant_id: int | None = None) -> dict:
        rules = self.list_rules(tenant_id=tenant_id)
        return {
            "total": len(rules),
            "enabled": sum(1 for r in rules if r.get("enabled")),
            "handover": sum(1 for r in rules if r.get("action") == "handover"),
            "stop": sum(1 for r in rules if r.get("action") == "stop"),
        }



    def delete_rule(self, rule_id: int, tenant_id: int | None = None) -> bool:
        with self._db(tenant_id) as session:
            obj = session.get(ComplianceRule, rule_id)
            if not obj:
                return False
            session.delete(obj)
            return True


compliance_manager = ComplianceManager()
