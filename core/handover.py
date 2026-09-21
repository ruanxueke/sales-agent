"""转人工：客户要求人工时生成接管请求并通知叙白"""
from __future__ import annotations
import logging

import requests
from sqlalchemy import select

from config.settings import settings
from core.db import init_db, session_scope
from core.models import HandoverRequest

logger = logging.getLogger(__name__)


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _target() -> str:
    return settings.LEAD_DEFAULT_OWNER or settings.SALES_NOTIFY_TARGET or "叙白"


class HandoverManager:
    def request(
        self,
        session_id: str,
        source: str = "wechat",
        nickname: str = "",
        reason: str = "",
    ) -> dict:
        init_db()
        lead = None
        customer = None
        try:
            from core.lead import lead_manager
            lead = lead_manager.get_by_session_id(session_id)
        except Exception as e:
            logger.debug("HandoverManager.request 异常已忽略: %s", e)
        try:
            from core.sales_crm import crm
            customer = crm.get_by_session(session_id)
        except Exception as e:
            logger.debug("HandoverManager.request 异常已忽略: %s", e)

        with session_scope() as session:
            obj = HandoverRequest(
                session_id=session_id,
                customer_id=customer["id"] if customer else None,
                lead_id=lead["id"] if lead else None,
                source=source,
                reason=reason[:500],
                status="requested",
                owner="",
            )
            session.add(obj)
            session.flush()
            request_id = obj.id

        content = (
            f"【转人工】客户要求人工对接\n"
            f"客户ID：{session_id}\n"
            f"昵称：{nickname or (lead or {}).get('nickname') or (customer or {}).get('nickname') or '未提供'}\n"
            f"来源：{source}\n"
            f"原因：{reason or '客户主动要求人工'}"
        )
        target = _target()
        if customer:
            try:
                from core.sales_crm import crm
                crm.create_notification(customer["id"], target, content)
            except Exception as e:
                logger.error(f"转人工通知落库失败: {e}")
        try:
            from core.bot_notify import send_bot_notify
            if send_bot_notify(target, content):
                logger.info("转人工通知已投递给 %s", target)
            else:
                logger.error("转人工通知投递失败: %s", target)
        except Exception as e:
            logger.error(f"转人工通知投递失败: {e}")
        return {"id": request_id, "status": "requested", "session_id": session_id}

    def assign(self, request_id: int, owner: str = "") -> dict | None:
        owner = owner.strip() or _target()
        init_db()
        with session_scope() as session:
            obj = session.get(HandoverRequest, request_id)
            if not obj:
                return None
            obj.owner = owner
            obj.status = "assigned"
            obj.assigned_at = _now()
            return self._dict(obj)

    def complete(self, request_id: int) -> dict | None:
        init_db()
        with session_scope() as session:
            obj = session.get(HandoverRequest, request_id)
            if not obj:
                return None
            obj.status = "done"
            obj.done_at = _now()
            return self._dict(obj)

    def list(self, status: str = "", limit: int = 200) -> list[dict]:
        init_db()
        with session_scope() as session:
            query = select(HandoverRequest).order_by(HandoverRequest.id.desc())
            if status:
                query = query.where(HandoverRequest.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [self._dict(r) for r in rows]

    def stats(self) -> dict:
        items = self.list(limit=100000)
        result = {"total": len(items), "by_status": {}}
        for item in items:
            status = item["status"] or "requested"
            result["by_status"][status] = result["by_status"].get(status, 0) + 1
        return result

    @staticmethod
    def _dict(obj) -> dict:
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


handover_manager = HandoverManager()
