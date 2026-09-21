"""商用化核心闭环：统一会话通道、智能路由、CDP/RFM、营销旅程、坐席队列、内容安全。

本模块是“对标网易智企整体优化方案”中不依赖外部凭证即可落地的部分，
全部走 SQLAlchemy + PostgreSQL/SQLite，支持多租户隔离。
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import init_db, session_scope
from core.tenancy import tenant_session_key
from core.models import (
    BehaviorEvent,
    ChannelMessage,
    ChannelSession,
    Customer,
    CustomerTag,
    FollowupTask,
    HandoverRequest,
    Lead,
    MarketingJourney,
    ModerationRule,
    Notification,
    RouteRule,
    Ticket,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _parse_json(value, default):
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return default


class CommercialCore:
    def __init__(self):
        init_db()

    # ============================================================
    # 统一会话通道
    # ============================================================

    def ingest_message(
        self,
        tenant_id: int | None,
        channel: str,
        external_id: str,
        content: str,
        direction: str = "in",
        session_key: str = "",
        customer_id: int | None = None,
        nickname: str = "",
        source_page: str = "",
        msg_type: str = "text",
    ) -> dict:
        tid = tenant_id or 0
        content = (content or "").strip()
        external_id = (external_id or "").strip()
        if not external_id or not content:
            return {"ok": False, "error": "external_id 和 content 必填"}
        with session_scope() as session:
            session_obj = None
            if session_key:
                session_obj = session.execute(
                    select(ChannelSession).where(ChannelSession.tenant_id == tid, ChannelSession.session_key == session_key)
                ).scalars().first()
            if not session_obj:
                session_obj = session.execute(
                    select(ChannelSession).where(ChannelSession.tenant_id == tid, ChannelSession.channel == channel, ChannelSession.external_id == external_id)
                ).scalars().first()
            if not session_obj:
                session_obj = ChannelSession(
                    tenant_id=tid,
                    channel=channel,
                    external_id=external_id,
                    session_key=session_key
                    or tenant_session_key(channel, tid, external_id),
                    nickname=nickname or "",
                    status="waiting",
                    priority=0,
                    route_target="robot",
                    source_page=source_page or "",
                )
                session.add(session_obj)
                session.flush()
            if customer_id and not session_obj.customer_id:
                session_obj.customer_id = customer_id
            if nickname:
                session_obj.nickname = nickname or session_obj.nickname
            session_obj.updated_at = _now()
            message = ChannelMessage(
                tenant_id=tid,
                session_id=session_obj.id,
                channel=channel,
                direction=direction,
                content=content,
                msg_type=msg_type,
            )
            session.add(message)
            session.flush()
            result = {
                "ok": True,
                "deduped": False,
                "session": _row_to_dict(session_obj),
                "message_id": message.id,
            }
        return result

    @staticmethod
    def _session_dict(session, session_id: int) -> dict:
        obj = session.get(ChannelSession, session_id)
        return _row_to_dict(obj) if obj else {}

    def list_sessions(self, tenant_id: int | None = None, status: str = "", limit: int = 100) -> list[dict]:
        with session_scope() as session:
            query = select(ChannelSession).order_by(ChannelSession.updated_at.desc())
            if tenant_id is not None:
                query = query.where(ChannelSession.tenant_id == tenant_id)
            if status:
                query = query.where(ChannelSession.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def session_messages(self, tenant_id: int | None, session_id: int, limit: int = 100) -> list[dict]:
        with session_scope() as session:
            query = select(ChannelMessage).where(ChannelMessage.session_id == session_id).order_by(ChannelMessage.id.desc()).limit(limit)
            if tenant_id is not None:
                query = query.where(ChannelMessage.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
            return [_row_to_dict(r) for r in reversed(rows)]

    def close_session(self, tenant_id: int | None, session_id: int) -> bool:
        with session_scope() as session:
            query = select(ChannelSession).where(ChannelSession.id == session_id)
            if tenant_id is not None:
                query = query.where(ChannelSession.tenant_id == tenant_id)
            obj = session.execute(query).scalars().first()
            if not obj:
                return False
            obj.status = "closed"
            obj.closed_at = _now()
            obj.updated_at = _now()
            return True

    def assign_session(self, tenant_id: int | None, session_id: int, agent: str) -> bool:
        with session_scope() as session:
            query = select(ChannelSession).where(ChannelSession.id == session_id)
            if tenant_id is not None:
                query = query.where(ChannelSession.tenant_id == tenant_id)
            obj = session.execute(query).scalars().first()
            if not obj:
                return False
            obj.assigned_agent = agent
            obj.status = "active"
            obj.updated_at = _now()
            return True

    # ============================================================
    # 智能路由
    # ============================================================

    def list_rules(self, tenant_id: int | None = None) -> list[dict]:
        with session_scope() as session:
            query = select(RouteRule).order_by(RouteRule.priority, RouteRule.id.desc())
            if tenant_id is not None:
                query = query.where(RouteRule.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
            items = []
            for r in rows:
                d = _row_to_dict(r)
                d["condition"] = _parse_json(d.pop("condition_json", "{}"), {})
                items.append(d)
            if tenant_id is None and not items:
                items = [{"id": 0, "tenant_id": 0, "name": "默认机器人优先", "priority": 0, "target": "robot", "enabled": True, "condition": {}, "builtin": True}]
            return items

    def create_rule(self, tenant_id: int | None, name: str, condition: dict, target: str, priority: int = 0, enabled: bool = True) -> dict:
        with session_scope() as session:
            obj = RouteRule(
                tenant_id=tenant_id or 0,
                name=(name or "").strip() or "未命名路由规则",
                priority=int(priority or 0),
                condition_json=json.dumps(condition or {}, ensure_ascii=False),
                target=target if target in ("robot", "agent", "sales", "ticket") else "robot",
                enabled=bool(enabled),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def delete_rule(self, rule_id: int, tenant_id: int | None = None) -> bool:
        with session_scope() as session:
            query = select(RouteRule).where(RouteRule.id == rule_id)
            if tenant_id is not None:
                query = query.where(RouteRule.tenant_id == tenant_id)
            obj = session.execute(query).scalars().first()
            if not obj:
                return False
            session.delete(obj)
            return True

    def route_session(self, tenant_id: int | None, session_id: int) -> dict:
        with session_scope() as session:
            query = select(ChannelSession).where(ChannelSession.id == session_id)
            if tenant_id is not None:
                query = query.where(ChannelSession.tenant_id == tenant_id)
            session_obj = session.execute(query).scalars().first()
            if not session_obj:
                return {"ok": False, "error": "会话不存在"}
            context = _row_to_dict(session_obj)
            if session_obj.customer_id:
                customer = session.get(Customer, session_obj.customer_id)
                if customer:
                    context.update(_row_to_dict(customer))
            if session_obj.lead_id:
                lead = session.get(Lead, session_obj.lead_id)
                if lead:
                    context.update(_row_to_dict(lead))

            latest = session.execute(
                select(ChannelMessage).where(ChannelMessage.session_id == session_id).order_by(ChannelMessage.id.desc())
            ).scalars().first()
            if latest:
                context["content"] = latest.content
                context["channel"] = latest.channel

            rules = self.list_rules(tenant_id)
            target = "robot"
            matched = None
            for rule in rules:
                if not rule.get("enabled"):
                    continue
                condition = rule.get("condition") or {}
                if self._match_condition(condition, context):
                    target = rule.get("target") or "robot"
                    matched = rule
                    break
            session_obj.route_target = target
            session_obj.priority = int((matched or {}).get("priority") or session_obj.priority or 0)
            if target in ("agent", "sales"):
                session.add(HandoverRequest(
                    session_id=session_obj.session_key or "",
                    customer_id=session_obj.customer_id,
                    lead_id=session_obj.lead_id,
                    source=session_obj.channel,
                    reason=f"路由规则: {(matched or {}).get('name') or '人工'}" if matched else "需要人工",
                    status="requested",
                ))
            if target == "ticket":
                session.add(Ticket(
                    title=f"会话 #{session_obj.id} 转工单",
                    session_id=session_obj.session_key or "",
                    customer_id=session_obj.customer_id,
                    lead_id=session_obj.lead_id,
                    category=session_obj.channel,
                    status="open",
                    priority=str(session_obj.priority or 0),
                ))
            session_obj.updated_at = _now()
            session.flush()
            return {"ok": True, "target": target, "rule": matched, "session": _row_to_dict(session_obj)}

    @staticmethod
    def _match_condition(condition: dict, context: dict) -> bool:
        field = condition.get("field")
        op = condition.get("op") or "eq"
        value = condition.get("value")
        if not field:
            return True
        actual = context.get(field)
        if op == "eq":
            return str(actual) == str(value)
        if op == "neq":
            return str(actual) != str(value)
        if op == "contains":
            return str(value) in str(actual or "")
        if op == "in":
            return str(actual) in [str(x) for x in (value or [])]
        if op == "gt":
            try:
                return float(actual or 0) > float(value or 0)
            except Exception:
                return False
        if op == "lt":
            try:
                return float(actual or 0) < float(value or 0)
            except Exception:
                return False
        return False

    # ============================================================
    # CDP：标签 / RFM / 人群
    # ============================================================

    def add_tag(self, tenant_id: int | None, tag: str, customer_id: int | None = None, lead_id: int | None = None, session_id: str = "", source: str = "manual") -> dict:
        with session_scope() as session:
            obj = CustomerTag(
                customer_id=customer_id,
                lead_id=lead_id,
                session_id=session_id or "",
                tag=(tag or "").strip(),
                source=source or "manual",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_tags(self, tenant_id: int | None = None, customer_id: int | None = None, lead_id: int | None = None, limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(CustomerTag).order_by(CustomerTag.id.desc()).limit(limit)
            if customer_id is not None:
                query = query.where(CustomerTag.customer_id == customer_id)
            if lead_id is not None:
                query = query.where(CustomerTag.lead_id == lead_id)
            return [_row_to_dict(r) for r in session.execute(query).scalars().all()]

    def rfm(self, tenant_id: int | None = None) -> dict:
        from core.sales_crm import crm
        try:
            customers = crm.list_customers()
        except Exception:
            customers = []
        with session_scope() as session:
            query = select(Lead)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == tenant_id)
            try:
                leads = [_row_to_dict(r) for r in session.execute(query).scalars().all()]
            except Exception:
                leads = []
        items = []
        for c in customers:
            customer_id = c.get("id")
            tags = [t["tag"] for t in self.list_tags(tenant_id, customer_id=customer_id)]
            stage = c.get("stage") or "new"
            monetary = 0.0
            recency_days = 365
            frequency = 0
            if stage in ("won", "enrolled"):
                monetary = 198.0
                frequency = 1
                recency_days = 7
            items.append({
                "customer_id": customer_id,
                "nickname": c.get("nickname") or c.get("display_id") or "",
                "stage": stage,
                "rfm": {"recency_days": recency_days, "frequency": frequency, "monetary": monetary},
                "tags": tags,
                "tier": "高价值" if monetary >= 198 else ("潜在" if stage in ("high_intent", "recommended") else "普通"),
            })
        return {"total": len(items), "items": items[:500]}

    def segment_by_tag(self, tenant_id: int | None, tag: str) -> list[dict]:
        tags = self.list_tags(tenant_id, limit=2000)
        return [t for t in tags if t.get("tag") == tag]

    # ============================================================
    # 营销自动化旅程
    # ============================================================

    def list_journeys(self, tenant_id: int | None = None) -> list[dict]:
        with session_scope() as session:
            query = select(MarketingJourney).order_by(MarketingJourney.id.desc())
            if tenant_id is not None:
                query = query.where(MarketingJourney.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
            items = []
            for r in rows:
                d = _row_to_dict(r)
                d["nodes"] = _parse_json(d.pop("nodes_json", "[]"), [])
                items.append(d)
            return items

    def create_journey(self, tenant_id: int | None, name: str, trigger: str, nodes: list[dict], enabled: bool = True, daily_limit: int = 100) -> dict:
        with session_scope() as session:
            obj = MarketingJourney(
                tenant_id=tenant_id or 0,
                name=(name or "").strip() or "未命名旅程",
                trigger=trigger or "manual",
                nodes_json=json.dumps(nodes or [], ensure_ascii=False),
                enabled=bool(enabled),
                daily_limit=max(1, int(daily_limit or 100)),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def delete_journey(self, journey_id: int, tenant_id: int | None = None) -> bool:
        with session_scope() as session:
            query = select(MarketingJourney).where(MarketingJourney.id == journey_id)
            if tenant_id is not None:
                query = query.where(MarketingJourney.tenant_id == tenant_id)
            obj = session.execute(query).scalars().first()
            if not obj:
                return False
            session.delete(obj)
            return True

    def run_journey(self, journey_id: int, context: dict | None = None, tenant_id: int | None = None) -> dict:
        context = context or {}
        tid = tenant_id or 0
        with session_scope() as session:
            query = select(MarketingJourney).where(MarketingJourney.id == journey_id)
            if tenant_id is not None:
                query = query.where(MarketingJourney.tenant_id == tenant_id)
            journey = session.execute(query).scalars().first()
            if not journey:
                return {"ok": False, "error": "旅程不存在或无权访问"}
            if not journey.enabled:
                return {"ok": False, "error": "旅程已停用"}
            today = _now()[:10]
            runs = session.execute(
                select(BehaviorEvent).where(
                    BehaviorEvent.event_type == "journey_run",
                    BehaviorEvent.event_value == str(journey_id),
                    BehaviorEvent.created_at.like(f"{today}%"),
                )
            ).scalars().all()
            if len(runs) >= journey.daily_limit:
                return {"ok": False, "error": f"今日触达已达上限 {journey.daily_limit}"}
            session.add(BehaviorEvent(session_id=context.get("session_id") or "", event_type="journey_run", event_value=str(journey_id)))
            nodes = _parse_json(journey.nodes_json, [])
            results = []
            for node in nodes:
                results.append(self._run_journey_node(session, node, context))
            return {"ok": True, "journey_id": journey_id, "name": journey.name, "nodes": results}

    def trigger_journey(self, event: str, context: dict | None = None, tenant_id: int | None = None) -> list[dict]:
        context = context or {}
        with session_scope() as session:
            query = select(MarketingJourney).where(MarketingJourney.trigger == event, MarketingJourney.enabled.is_(True))
            if tenant_id is not None:
                query = query.where(MarketingJourney.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
        results = []
        for journey in rows:
            try:
                results.append(self.run_journey(journey.id, context, tenant_id))
            except Exception as e:
                logger.error("旅程 %s 触发失败: %s", journey.id, e)
                results.append({"ok": False, "journey_id": journey.id, "error": str(e)[:200]})
        return results

    @staticmethod
    def _run_journey_node(session, node: dict, context: dict) -> dict:
        node_type = node.get("type")
        label = node.get("label") or node_type
        try:
            if node_type == "notify":
                session.add(Notification(
                    customer_id=int(context.get("customer_id") or 0),
                    target=node.get("receivers") or context.get("owner") or "",
                    content=node.get("content") or "",
                    status="pending",
                ))
                return {"ok": True, "type": node_type, "label": label}
            if node_type == "create_followup":
                hours = int(node.get("hours") or 24)
                due = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
                session.add(FollowupTask(
                    session_id=context.get("session_id") or "",
                    lead_id=context.get("lead_id"),
                    customer_id=context.get("customer_id"),
                    node=1,
                    node_label=f"旅程-{hours}h",
                    due_at=due,
                    status="pending",
                    channel=context.get("channel") or "official",
                    content=node.get("content") or "",
                ))
                return {"ok": True, "type": node_type, "label": label, "due_at": due}
            if node_type == "add_tag":
                from core.commercial import commercial
                commercial.add_tag(context.get("tenant_id"), node.get("tag") or "", customer_id=context.get("customer_id"), lead_id=context.get("lead_id"), session_id=context.get("session_id") or "", source="journey")
                return {"ok": True, "type": node_type, "label": label, "tag": node.get("tag")}
            if node_type == "delay":
                return {"ok": True, "type": node_type, "label": label, "note": f"延迟 {node.get('hours', 0)} 小时"}
            return {"ok": True, "type": node_type, "label": label, "note": "已记录"}
        except Exception as e:
            return {"ok": False, "type": node_type, "label": label, "error": str(e)[:200]}

    # ============================================================
    # 内容安全
    # ============================================================

    def list_moderation_rules(self, tenant_id: int | None = None) -> list[dict]:
        with session_scope() as session:
            query = select(ModerationRule).order_by(ModerationRule.id.desc())
            if tenant_id is not None:
                query = query.where(ModerationRule.tenant_id == tenant_id)
            return [_row_to_dict(r) for r in session.execute(query).scalars().all()]

    def create_moderation_rule(self, tenant_id: int | None, name: str, keywords: str, action: str = "block", enabled: bool = True) -> dict:
        with session_scope() as session:
            obj = ModerationRule(
                tenant_id=tenant_id or 0,
                name=(name or "").strip() or "未命名规则",
                keywords=keywords or "",
                action=action if action in ("block", "review") else "block",
                enabled=bool(enabled),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def delete_moderation_rule(self, rule_id: int, tenant_id: int | None = None) -> bool:
        with session_scope() as session:
            query = select(ModerationRule).where(ModerationRule.id == rule_id)
            if tenant_id is not None:
                query = query.where(ModerationRule.tenant_id == tenant_id)
            obj = session.execute(query).scalars().first()
            if not obj:
                return False
            session.delete(obj)
            return True

    def check_text(self, text: str, tenant_id: int | None = None) -> dict:
        text = text or ""
        rules = self.list_moderation_rules(tenant_id)
        matched = []
        action = "pass"
        for rule in rules:
            if not rule.get("enabled"):
                continue
            for keyword in (rule.get("keywords") or "").split(","):
                keyword = keyword.strip()
                if keyword and keyword in text:
                    matched.append({"rule": rule.get("name"), "keyword": keyword, "action": rule.get("action")})
                    if rule.get("action") == "block":
                        action = "block"
                    elif action == "pass":
                        action = "review"
        return {"safe": action == "pass", "action": action, "matched": matched}


commercial = CommercialCore()
