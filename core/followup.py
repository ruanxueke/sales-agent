"""自动跟进：1h/1d/3d/7d 节点计划、到期触达与结果回写"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

import requests
from sqlalchemy import select

from config.settings import settings
from core.db import init_db, session_scope
from core.models import FollowupTask

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATES = [
    "您好，我是刚才和您沟通的课程顾问。刚才聊到的AI学习方向，我整理了一份资料，方便您先看看。",
    "您好，昨天聊完后，您这边有没有进一步想了解的？我可以针对您的情况给具体建议。",
    "您好，这几天考虑得怎么样？如果还有犹豫的地方，可以随时和我说，我再帮您梳理。",
    "您好，想再和您确认一下，目前还有在了解AI课程吗？如果暂时不需要，也没关系，以后有需要随时找我。",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def followup_nodes() -> list[tuple[str, int]]:
    raw = [x.strip() for x in (settings.FOLLOWUP_NODES_HOURS or "1,24,72,168").split(",") if x.strip()]
    labels = ["2h", "1d", "3d", "7d", "14d", "30d"]
    nodes = []
    for index, hours in enumerate(raw):
        try:
            nodes.append((labels[index] if index < len(labels) else f"n{index + 1}", int(hours)))
        except ValueError:
            continue
    return nodes or [("2h", 2), ("1d", 24), ("3d", 72), ("7d", 168), ("14d", 336), ("30d", 720)]


def _template(node_index: int, subject: dict) -> str:
    templates = DEFAULT_TEMPLATES
    if node_index >= len(templates):
        return templates[-1]
    return templates[node_index]


def _script_content(node_index: int, subject: dict) -> tuple[str, int | None]:
    """优先使用弹药库跟进话术，缺省时使用默认模板"""
    script_id = None
    try:
        from core.ammo import ammo_manager
        scene = (subject or {}).get("sales_status") or ""
        scripts = ammo_manager.list_scripts(scene=scene or "", active_only=True) if scene else []
        if node_index < len(scripts):
            script = scripts[node_index]
            content = script.get("script_example") or script.get("value_point") or ""
            if content:
                nickname = (subject or {}).get("nickname") or (subject or {}).get("name") or "您好"
                return content.replace("{nickname}", nickname), script.get("id")
    except Exception as e:
        logger.warning(f"跟进话术库读取失败，使用默认模板: {e}")
    return _template(node_index, subject), script_id


class FollowupEngine:
    def plan_for_customer(self, customer: dict) -> int:
        session_id = customer.get("session_id") or ""
        if not session_id:
            return 0
        if self._has_pending(session_id):
            return 0
        source = customer.get("source") or "wechat"
        channel = "official" if source == "official" else "wechat"
        return self._create_tasks(
            session_id=session_id,
            lead_id=None,
            customer_id=customer.get("id"),
            subject=customer,
            channel=channel,
        )

    def plan_for_lead(self, lead: dict, customer: dict = None) -> int:
        session_id = lead.get("session_id") or ""
        if not session_id:
            return 0
        if self._has_pending(session_id):
            return 0
        source = lead.get("source") or "import"
        channel = "official" if source == "official" else "wechat"
        return self._create_tasks(
            session_id=session_id,
            lead_id=lead.get("id"),
            customer_id=customer.get("id") if customer else lead.get("customer_id"),
            subject=lead,
            channel=channel,
        )

    def _has_pending(self, session_id: str) -> bool:
        init_db()
        with session_scope() as session:
            count = session.execute(
                select(FollowupTask).where(
                    FollowupTask.session_id == session_id,
                    FollowupTask.status == "pending",
                )
            ).scalars().all()
            return len(count) > 0

    def _create_tasks(self, session_id, lead_id, customer_id, subject, channel) -> int:
        created = 0
        now = datetime.now()
        for index, (label, hours) in enumerate(followup_nodes()):
            due = (now + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            content, script_id = _script_content(index, subject)
            with session_scope() as session:
                session.add(FollowupTask(
                    session_id=session_id,
                    lead_id=lead_id,
                    customer_id=customer_id,
                    node=index + 1,
                    node_label=label,
                    due_at=due,
                    status="pending",
                    channel=channel,
                    content=content,
                    source_script_id=script_id,
                ))
                created += 1
        return created

    def dispatch_due(self, limit: int = 50) -> int:
        if not settings.FOLLOWUP_ENABLED:
            return 0
        init_db()
        sent = 0
        with session_scope() as session:
            rows = session.execute(
                select(FollowupTask)
                .where(FollowupTask.status == "pending", FollowupTask.due_at <= _now())
                .order_by(FollowupTask.due_at)
                .limit(limit)
            ).scalars().all()
            for task in rows:
                ok, reason = self._send_task(task)
                if self._is_rejected(task):
                    task.status = "skipped"
                    task.result = "rejected_stop"
                    task.updated_at = _now()
                    logger.info(f"跟进任务 #{task.id} 客户已明确拒绝，停止触达")
                    continue
                if ok:
                    task.status = "sent"
                    task.sent_at = _now()
                    task.updated_at = _now()
                    sent += 1
                    self._after_sent(task)
                else:
                    task.status = "skipped"
                    task.updated_at = _now()
                    logger.warning(f"跟进任务 #{task.id} 发送失败: {reason}")
        return sent

    @staticmethod
    def _is_rejected(task: FollowupTask) -> bool:
        try:
            from core.sales_crm import crm
            if task.customer_id:
                customer = crm.get(task.customer_id)
                if customer and customer.get("sales_status") == "rejected":
                    return True
        except Exception as e:
            logger.debug("FollowupEngine._is_rejected 异常已忽略: %s", e)
        try:
            from core.lead import lead_manager
            if task.lead_id:
                lead = lead_manager.get(task.lead_id)
                if lead and lead.get("sales_status") == "rejected":
                    return True
        except Exception as e:
            logger.debug("FollowupEngine._is_rejected 异常已忽略: %s", e)
        return False

    def _send_task(self, task: FollowupTask) -> tuple[bool, str]:
        if task.channel == "official":
            try:
                from connectors.wechat_official import official_client
                if not settings.WECHAT_OFFICIAL_APP_ID:
                    return False, "公众号未配置"
                official_client.send_text(task.session_id, task.content)
                return True, ""
            except Exception as e:
                return False, str(e)
        if task.channel == "wechat":
            try:
                from core.bot_notify import send_bot_notify
                if send_bot_notify(self._target_name(task), task.content):
                    return True, ""
                return False, "通知投递失败"
            except Exception as e:
                return False, str(e)
        return False, f"未知通道: {task.channel}"

    def _target_name(self, task: FollowupTask) -> str:
        if task.customer_id:
            try:
                from core.sales_crm import crm
                customer = crm.get(task.customer_id)
                if customer:
                    return customer.get("nickname") or customer.get("name") or ""
            except Exception as e:
                logger.debug("FollowupEngine._target_name 异常已忽略: %s", e)
        if task.lead_id:
            try:
                from core.lead import lead_manager
                lead = lead_manager.get(task.lead_id)
                if lead:
                    return lead.get("nickname") or lead.get("name") or ""
            except Exception as e:
                logger.debug("FollowupEngine._target_name 异常已忽略: %s", e)
        return ""

    def _after_sent(self, task: FollowupTask) -> None:
        if task.customer_id:
            try:
                from core.sales_crm import crm
                crm.append_chat(task.customer_id, "客服", task.content)
                next_due = self._next_due(task.session_id)
                if next_due:
                    crm.update_profile(task.customer_id, next_follow_up=next_due)
            except Exception as e:
                logger.error(f"跟进回写客户失败: {e}")
        if task.lead_id:
            try:
                from core.lead import lead_manager
                next_due = self._next_due(task.session_id)
                updates = {"last_follow_at": _now()}
                if next_due:
                    updates["next_follow_up"] = next_due
                lead_manager.update(task.lead_id, **updates)
            except Exception as e:
                logger.error(f"跟进回写线索失败: {e}")

    def _next_due(self, session_id: str) -> str:
        with session_scope() as session:
            row = session.execute(
                select(FollowupTask)
                .where(
                    FollowupTask.session_id == session_id,
                    FollowupTask.status == "pending",
                )
                .order_by(FollowupTask.due_at)
                .limit(1)
            ).scalars().first()
            return row.due_at if row else ""

    def list_tasks(self, status: str = "", limit: int = 200) -> list[dict]:
        init_db()
        with session_scope() as session:
            query = select(FollowupTask).order_by(FollowupTask.due_at)
            if status:
                query = query.where(FollowupTask.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rows
            ]

    def stats(self) -> dict:
        tasks = self.list_tasks(limit=100000)
        result = {"total": len(tasks), "by_status": {}}
        for task in tasks:
            status = task["status"] or "pending"
            result["by_status"][status] = result["by_status"].get(status, 0) + 1
        result["pending"] = result["by_status"].get("pending", 0)
        result["sent"] = result["by_status"].get("sent", 0)
        return result


followup_engine = FollowupEngine()
