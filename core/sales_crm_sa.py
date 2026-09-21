"""客户档案 SQLAlchemy 后端：支持 MySQL / PostgreSQL / SQLite"""
from __future__ import annotations
import logging

from sqlalchemy import delete, select

from config.settings import settings
from core.db import session_scope
from core.models import (
    Customer,
    CustomerChatArchive,
    CustomerChatLog,
    Notification,
    StageLog,
)
from core.sales_constants import PROFILE_FIELDS, STAGE_RANK

logger = logging.getLogger(__name__)


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class SQLAlchemyCRM:
    """使用 SQLAlchemy 的客户档案后端"""

    @staticmethod
    def _now() -> str:
        from core.sales_crm import _now
        return _now()

    def get_or_create(
        self,
        session_id: str,
        nickname: str = "",
        source: str = "wechat",
        tenant_id: int | None = None,
    ) -> dict:
        with session_scope() as session:
            query = select(Customer).where(Customer.session_id == session_id)
            if tenant_id is not None:
                query = query.where(Customer.tenant_id == int(tenant_id))
            obj = session.execute(query).scalar_one_or_none()
            if obj:
                if nickname and obj.nickname != nickname:
                    old_name = str(obj.nickname or "").strip()
                    obj.nickname = nickname
                    obj.updated_at = self._now()
                    if self._display_id_follows_name(obj.display_id, old_name):
                        obj.display_id = self._make_display_id(
                            session,
                            nickname,
                            exclude_id=obj.id,
                            tenant_id=tenant_id,
                        )
                    session.flush()
                if nickname and not obj.display_id:
                    obj.display_id = self._make_display_id(
                        session,
                        nickname,
                        exclude_id=obj.id,
                        tenant_id=tenant_id,
                    )
                    obj.updated_at = self._now()
                    session.flush()
                return _row_to_dict(obj)
            obj = Customer(
                tenant_id=int(tenant_id or 0),
                session_id=session_id,
                nickname=nickname or "",
                source=source,
            )
            session.add(obj)
            session.flush()
            if nickname:
                obj.display_id = self._make_display_id(
                    session,
                    nickname,
                    tenant_id=tenant_id,
                )
                session.flush()
            return _row_to_dict(obj)

    def get(self, customer_id: int, tenant_id: int | None = None):
        with session_scope() as session:
            query = select(Customer).where(Customer.id == customer_id)
            if tenant_id is not None:
                query = query.where(Customer.tenant_id == int(tenant_id))
            obj = session.execute(query).scalar_one_or_none()
            return _row_to_dict(obj) if obj else None

    def get_by_session(self, session_id: str, tenant_id: int | None = None):
        with session_scope() as session:
            query = select(Customer).where(Customer.session_id == session_id)
            if tenant_id is not None:
                query = query.where(Customer.tenant_id == int(tenant_id))
            obj = session.execute(query).scalar_one_or_none()
            return _row_to_dict(obj) if obj else None

    def list_customers(self, tenant_id: int | None = None) -> list[dict]:
        with session_scope() as session:
            query = select(Customer)
            if tenant_id is not None:
                query = query.where(Customer.tenant_id == int(tenant_id))
            rows = session.execute(
                query.order_by(Customer.updated_at.desc())
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def update_profile(
        self,
        customer_id: int,
        tenant_id: int | None = None,
        **fields,
    ) -> None:
        allowed = {k: v for k, v in fields.items() if k in PROFILE_FIELDS}
        if not allowed:
            return
        with session_scope() as session:
            query = select(Customer).where(Customer.id == customer_id)
            if tenant_id is not None:
                query = query.where(Customer.tenant_id == int(tenant_id))
            obj = session.execute(query).scalar_one_or_none()
            if not obj:
                return
            if "nickname" in allowed and not obj.display_id:
                allowed["display_id"] = self._make_display_id(
                    session,
                    allowed["nickname"],
                    exclude_id=obj.id,
                    tenant_id=tenant_id,
                )
            for k, v in allowed.items():
                setattr(obj, k, v)
            obj.updated_at = self._now()

    def advance_stage(
        self,
        customer_id: int,
        new_stage: str,
        trigger: str = "",
        tenant_id: int | None = None,
    ) -> str:
        if new_stage not in STAGE_RANK:
            raise ValueError(f"未知阶段: {new_stage}")
        with session_scope() as session:
            query = select(Customer).where(Customer.id == customer_id)
            if tenant_id is not None:
                query = query.where(Customer.tenant_id == int(tenant_id))
            obj = session.execute(query).scalar_one_or_none()
            if not obj:
                return "new"
            old_stage = obj.stage or "new"
            if old_stage == new_stage:
                return old_stage
            obj.stage = new_stage
            obj.updated_at = self._now()
            session.add(StageLog(
                tenant_id=int(tenant_id or 0),
                customer_id=customer_id,
                from_stage=old_stage,
                to_stage=new_stage,
                trigger=trigger[:200],
            ))
            logger.info("客户 %s 阶段变化: %s -> %s (%s)", customer_id, old_stage, new_stage, trigger[:50])
            result = new_stage
        try:
            from core.sop import sop_manager
            sop_manager.on_stage_change(customer_id, new_stage)
        except Exception as e:
            logger.error(f"SOP阶段联动失败: {e}")
        return result

    @staticmethod
    def _display_id_follows_name(display_id: str, old_name: str) -> bool:
        display_id = str(display_id or "").strip()
        old_name = str(old_name or "").strip()
        if not display_id:
            return True
        if old_name and display_id == old_name:
            return True
        if old_name and display_id.startswith(old_name):
            return display_id[len(old_name):].isdigit()
        return False

    @staticmethod
    def _make_display_id(
        session,
        nickname: str,
        exclude_id: int | None = None,
        tenant_id: int | None = None,
    ) -> str:
        nickname = (nickname or "").strip()
        if not nickname:
            return ""
        query = select(Customer).where(Customer.display_id != "")
        if tenant_id is not None:
            query = query.where(Customer.tenant_id == int(tenant_id))
        if exclude_id is not None:
            query = query.where(Customer.id != exclude_id)
        used = {r.display_id for r in session.execute(query).scalars().all()}
        if nickname not in used:
            return nickname
        index = 2
        while f"{nickname}{index}" in used:
            index += 1
        return f"{nickname}{index}"


    def stage_log(self, customer_id: int, tenant_id: int | None = None) -> list[dict]:
        with session_scope() as session:
            query = select(StageLog).where(StageLog.customer_id == customer_id)
            if tenant_id is not None:
                query = query.where(StageLog.tenant_id == int(tenant_id))
            rows = session.execute(query.order_by(StageLog.id)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def append_chat(
        self,
        customer_id: int,
        role: str,
        content: str,
        tenant_id: int | None = None,
    ) -> None:
        with session_scope() as session:
            session.add(
                CustomerChatLog(
                    tenant_id=int(tenant_id or 0),
                    customer_id=customer_id,
                    role=role,
                    content=content,
                )
            )
            session.flush()
            self._trim_chat_log(session, customer_id)

    def _trim_chat_log(self, session, customer_id: int) -> None:
        max_entries = settings.CHAT_LOG_MAX_ENTRIES_PER_CUSTOMER
        rows = session.execute(
            select(CustomerChatLog)
            .where(CustomerChatLog.customer_id == customer_id)
            .order_by(CustomerChatLog.id)
        ).scalars().all()
        overflow = len(rows) - max_entries
        if overflow > 0:
            for row in rows[:overflow]:
                session.add(CustomerChatArchive(
                    tenant_id=int(getattr(row, "tenant_id", 0) or 0),
                    customer_id=customer_id,
                    role=row.role,
                    content=row.content,
                    created_at=row.created_at,
                ))
                session.delete(row)
            session.flush()
            archive_rows = session.execute(
                select(CustomerChatArchive)
                .where(CustomerChatArchive.customer_id == customer_id)
                .order_by(CustomerChatArchive.id)
            ).scalars().all()
            archive_cap = settings.CHAT_LOG_ARCHIVE_MAX_ENTRIES_PER_CUSTOMER
            if len(archive_rows) > archive_cap:
                for row in archive_rows[:len(archive_rows) - archive_cap]:
                    session.delete(row)

    def get_chat_log(
        self,
        customer_id: int,
        limit: int = 50,
        tenant_id: int | None = None,
    ) -> list[dict]:
        with session_scope() as session:
            query = select(CustomerChatLog).where(
                CustomerChatLog.customer_id == customer_id
            )
            if tenant_id is not None:
                query = query.where(CustomerChatLog.tenant_id == int(tenant_id))
            rows = session.execute(
                query.order_by(CustomerChatLog.id.desc()).limit(limit)
            ).scalars().all()
            return [_row_to_dict(r) for r in reversed(rows)]

    def create_notification(
        self,
        customer_id: int,
        target: str,
        content: str,
        status: str = "pending",
        tenant_id: int | None = None,
    ) -> int:
        with session_scope() as session:
            obj = Notification(
                tenant_id=int(tenant_id or 0),
                customer_id=customer_id,
                target=target,
                content=content,
                status=status,
            )
            session.add(obj)
            session.flush()
            return obj.id

    def list_notifications(
        self,
        limit: int = 100,
        tenant_id: int | None = None,
    ) -> list[dict]:
        with session_scope() as session:
            query = select(Notification)
            if tenant_id is not None:
                query = query.where(Notification.tenant_id == int(tenant_id))
            rows = session.execute(
                query.order_by(Notification.id.desc()).limit(limit)
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def update_notification_status(self, notification_id: int, status: str) -> None:
        with session_scope() as session:
            obj = session.get(Notification, notification_id)
            if obj:
                obj.status = status

    def count_today_messages(self, tenant_id: int | None = None) -> int:
        with session_scope() as session:
            from sqlalchemy import func
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            query = select(func.count()).select_from(CustomerChatLog).where(
                CustomerChatLog.created_at.like(today + "%")
            )
            if tenant_id is not None:
                query = query.where(CustomerChatLog.tenant_id == int(tenant_id))
            return session.execute(query).scalar_one() or 0
