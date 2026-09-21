"""个性化培育：按阶段/意向/行为触发，模板变量替换后自动触达"""
from __future__ import annotations
import logging
import requests
from datetime import datetime, timedelta

from sqlalchemy import select

from config.settings import settings
from core.db import init_db, session_scope
from core.models import NurtureCampaign, NurtureEvent, NurtureRule

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class NurtureManager:
    def __init__(self):
        init_db()

    # ---------- 培育计划 ----------
    def create_campaign(self, name, trigger_type="stage", trigger_value="", description="") -> dict:
        with session_scope() as session:
            obj = NurtureCampaign(
                name=name or "未命名培育计划",
                status="draft",
                trigger_type=trigger_type or "stage",
                trigger_value=trigger_value or "",
                description=description or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_campaign(self, campaign_id: int, **fields) -> dict | None:
        allowed = {"name", "status", "trigger_type", "trigger_value", "description"}
        with session_scope() as session:
            obj = session.get(NurtureCampaign, campaign_id)
            if not obj:
                return None
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(obj, key, value)
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    def list_campaigns(self, status="", limit=500) -> list[dict]:
        with session_scope() as session:
            query = select(NurtureCampaign).order_by(NurtureCampaign.id.desc())
            if status:
                query = query.where(NurtureCampaign.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 规则 ----------
    def add_rule(self, campaign_id: int, sequence: int, content: str, condition_type="always", condition_value="", delay_hours=0) -> dict | None:
        with session_scope() as session:
            campaign = session.get(NurtureCampaign, campaign_id)
            if not campaign:
                return None
            obj = NurtureRule(
                campaign_id=campaign_id,
                sequence=int(sequence or 1),
                condition_type=condition_type or "always",
                condition_value=condition_value or "",
                content=content or "",
                delay_hours=int(delay_hours or 0),
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_rules(self, campaign_id: int = 0, limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(NurtureRule).order_by(NurtureRule.campaign_id, NurtureRule.sequence)
            if campaign_id:
                query = query.where(NurtureRule.campaign_id == campaign_id)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    # ---------- 触达 ----------
    def dispatch_due(self, limit: int = 100) -> dict:
        campaigns = [c for c in self.list_campaigns(status="running", limit=1000)]
        rules = self.list_rules(limit=10000)
        created = 0
        sent = 0
        for campaign in campaigns:
            subjects = self._subjects(campaign)
            campaign_rules = [r for r in rules if r.get("campaign_id") == campaign["id"]]
            for subject in subjects:
                session_id = subject.get("session_id") or ""
                if not session_id:
                    continue
                for rule in campaign_rules:
                    if not self._rule_matches(rule, subject):
                        continue
                    due = self._due_at(subject, rule)
                    if due and due > _now():
                        continue
                    if self._already_created(campaign["id"], rule["id"], session_id):
                        continue
                    content = self._render(rule.get("content") or "", subject)
                    event = self._create_event(campaign["id"], rule["id"], session_id, subject, content)
                    created += 1
                    ok, reason = self._send(subject, content)
                    if ok:
                        self._mark_sent(event["id"])
                        sent += 1
                    else:
                        logger.warning("培育消息发送失败 %s: %s", session_id, reason)
        return {"created": created, "sent": sent}

    def _subjects(self, campaign: dict) -> list[dict]:
        try:
            from core.sales_crm import crm
            customers = crm.list_customers()
        except Exception:
            customers = []
        trigger_type = campaign.get("trigger_type") or "stage"
        trigger_value = campaign.get("trigger_value") or ""
        result = []
        for c in customers:
            if trigger_type == "stage" and c.get("stage") != trigger_value:
                continue
            if trigger_type == "intent" and c.get("intent_level") != trigger_value:
                continue
            if trigger_type == "event":
                # 行为事件触发：匹配最近行为事件
                try:
                    from core.sales_crm import crm
                    events = crm.get_chat_log(c.get("id"), limit=20)
                    hit = any(trigger_value in (str(e.get("content") or "") + str(e.get("role") or "")) for e in events)
                    if not hit:
                        continue
                except Exception:
                    continue
            result.append(c)
        return result

    @staticmethod
    def _rule_matches(rule: dict, subject: dict) -> bool:
        cond_type = rule.get("condition_type") or "always"
        cond_value = rule.get("condition_value") or ""
        if cond_type == "stage" and subject.get("stage") != cond_value:
            return False
        if cond_type == "intent" and subject.get("intent_level") != cond_value:
            return False
        if cond_type == "budget" and cond_value and cond_value not in str(subject.get("budget") or ""):
            return False
        return True

    @staticmethod
    def _due_at(subject: dict, rule: dict) -> str:
        created = subject.get("created_at") or ""
        delay = int(rule.get("delay_hours") or 0)
        try:
            base = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return _now()
        return (base + timedelta(hours=delay)).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _render(content: str, subject: dict) -> str:
        replacements = {
            "{nickname}": subject.get("nickname") or subject.get("name") or "您好",
            "{name}": subject.get("name") or subject.get("nickname") or "",
            "{goal}": subject.get("goal") or "",
            "{budget}": subject.get("budget") or "",
            "{interest}": subject.get("interest") or "",
            "{product}": subject.get("interest") or "",
            "{stage}": subject.get("stage") or "",
            "{intent_level}": subject.get("intent_level") or "",
        }
        for key, value in replacements.items():
            content = content.replace(key, value)
        return content

    def _already_created(self, campaign_id: int, rule_id: int, session_id: str) -> bool:
        with session_scope() as session:
            row = session.execute(
                select(NurtureEvent).where(
                    NurtureEvent.campaign_id == campaign_id,
                    NurtureEvent.rule_id == rule_id,
                    NurtureEvent.session_id == session_id,
                )
            ).scalars().first()
            return row is not None

    def _create_event(self, campaign_id, rule_id, session_id, subject, content) -> dict:
        with session_scope() as session:
            obj = NurtureEvent(
                campaign_id=campaign_id,
                rule_id=rule_id,
                customer_id=subject.get("id"),
                lead_id=None,
                session_id=session_id,
                personalized_content=content,
                status="pending",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def _mark_sent(self, event_id: int) -> None:
        with session_scope() as session:
            obj = session.get(NurtureEvent, event_id)
            if obj:
                obj.status = "sent"
                obj.sent_at = _now()
                obj.updated_at = _now()

    def _send(self, subject: dict, content: str) -> tuple[bool, str]:
        session_id = subject.get("session_id") or ""
        source = subject.get("source") or "wechat"
        if source == "official":
            try:
                from connectors.wechat_official import official_client
                official_client.send_text(session_id, content)
                return True, ""
            except Exception as e:
                return False, str(e)
        try:
            from core.bot_notify import send_bot_notify
            if send_bot_notify(subject.get("nickname") or subject.get("name") or "", content):
                return True, ""
            return False, "通知投递失败"
        except Exception as e:
            return False, str(e)

    def stats(self) -> dict:
        campaigns = self.list_campaigns(limit=100000)
        rules = self.list_rules(limit=100000)
        events = self.list_events(limit=100000)
        return {
            "campaigns": len(campaigns),
            "running": sum(1 for c in campaigns if c.get("status") == "running"),
            "rules": len(rules),
            "events": len(events),
            "sent": sum(1 for e in events if e.get("status") == "sent"),
            "pending": sum(1 for e in events if e.get("status") == "pending"),
        }

    def list_events(self, status: str = "", limit: int = 500) -> list[dict]:
        with session_scope() as session:
            query = select(NurtureEvent).order_by(NurtureEvent.id.desc())
            if status:
                query = query.where(NurtureEvent.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]


nurture_manager = NurtureManager()
