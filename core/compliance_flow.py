"""合规流程：授权留存、正式数据删除请求与租户内删除执行。"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import delete, select

from core.db import init_db, session_scope
from core.models import (
    BehaviorEvent,
    ChannelMessage,
    ChannelSession,
    ConsentLog,
    Customer,
    CustomerChatArchive,
    CustomerChatLog,
    CustomerTag,
    DeletionRequest,
    FollowupTask,
    Notification,
    StageLog,
)

logger = logging.getLogger(__name__)


class EraseIncomplete(RuntimeError):
    """删除请求未彻底执行，必须保持 failed 并可重试。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ComplianceFlow:
    def __init__(self):
        init_db()

    def add_consent(
        self,
        session_id: str,
        source: str = "",
        content: str = "",
        tenant_id: int = 0,
    ) -> dict:
        with session_scope() as session:
            row = ConsentLog(
                tenant_id=int(tenant_id or 0),
                session_id=session_id,
                source=source,
                content=content,
                status="granted",
                created_at=_now(),
            )
            session.add(row)
            session.flush()
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def list_consents(
        self,
        session_id: str = "",
        limit: int = 200,
        tenant_id: int | None = None,
    ) -> list[dict]:
        with session_scope(read_only=True) as session:
            query = select(ConsentLog)
            if tenant_id is not None:
                query = query.where(ConsentLog.tenant_id == int(tenant_id))
            if session_id:
                query = query.where(ConsentLog.session_id == session_id)
            rows = session.execute(
                query.order_by(ConsentLog.id.desc()).limit(limit)
            ).scalars().all()
            return [
                {column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in rows
            ]

    def request_deletion(
        self,
        session_id: str,
        applicant: str = "",
        reason: str = "",
        tenant_id: int = 0,
    ) -> dict:
        with session_scope() as session:
            row = DeletionRequest(
                tenant_id=int(tenant_id or 0),
                session_id=session_id,
                applicant=applicant,
                reason=reason,
                status="pending",
                result_json="{}",
                created_at=_now(),
            )
            session.add(row)
            session.flush()
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def list_deletion_requests(
        self,
        status: str = "",
        limit: int = 200,
        tenant_id: int | None = None,
    ) -> list[dict]:
        with session_scope(read_only=True) as session:
            query = select(DeletionRequest)
            if tenant_id is not None:
                query = query.where(DeletionRequest.tenant_id == int(tenant_id))
            if status:
                query = query.where(DeletionRequest.status == status)
            rows = session.execute(
                query.order_by(DeletionRequest.id.desc()).limit(limit)
            ).scalars().all()
            return [
                {column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in rows
            ]

    def confirm_deletion(
        self,
        request_id: int,
        handler: str = "admin",
        tenant_id: int | None = None,
    ) -> dict:
        with session_scope() as session:
            query = select(DeletionRequest).where(DeletionRequest.id == request_id)
            if tenant_id is not None:
                query = query.where(DeletionRequest.tenant_id == int(tenant_id))
            row = session.execute(query).scalars().first()
            if not row:
                return {"ok": False, "error": "请求不存在"}
            row.attempts = int(row.attempts or 0) + 1
            session.flush()
            session_id = row.session_id
            request_tenant = int(row.tenant_id or 0)

        try:
            erased = self._erase_session(session_id, tenant_id=request_tenant)
        except EraseIncomplete as exc:
            detail = str(exc)[:1000]
            with session_scope() as session:
                row = session.get(DeletionRequest, request_id)
                if row:
                    row.status = "failed"
                    row.error = detail
                    row.handler = handler
                    row.handled_at = _now()
                    row.next_retry_at = _now()
            self._audit_deletion(
                handler,
                session_id,
                request_id,
                "failed: " + detail,
                "critical",
                request_tenant,
            )
            return {"ok": False, "erased": False, "error": "删除未完成: " + detail}

        with session_scope() as session:
            row = session.get(DeletionRequest, request_id)
            if row:
                row.status = "done"
                row.handler = handler
                row.handled_at = _now()
                row.error = ""
                row.result_json = '{"erased": %s}' % ("true" if erased else "false")
            updated = (
                {column.name: getattr(row, column.name) for column in row.__table__.columns}
                if row
                else None
            )
        self._audit_deletion(
            handler,
            session_id,
            request_id,
            f"erased={erased}",
            "critical",
            request_tenant,
        )
        return {"ok": True, "erased": erased, "request": updated}

    def erase_customer(
        self,
        session_id: str,
        tenant_id: int,
        actor: str = "admin",
    ) -> dict:
        try:
            erased = self._erase_session(session_id, tenant_id=tenant_id)
        except EraseIncomplete as exc:
            return {"erased": False, "error": str(exc)}
        self._audit_deletion(
            actor,
            session_id,
            "direct",
            f"erased={erased}",
            "warn",
            tenant_id,
        )
        return {"erased": erased}

    @staticmethod
    def _audit_deletion(
        handler: str,
        session_id: str,
        request_id,
        detail: str,
        level: str,
        tenant_id: int,
    ) -> None:
        try:
            from core.audit import audit

            audit(
                actor=handler,
                action="deletion_executed",
                resource=session_id,
                detail=f"request={request_id} {detail}",
                level=level,
                category="sensitive",
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.error("删除执行审计写入失败: %s", exc)

    def _erase_session(self, session_id: str, tenant_id: int) -> bool:
        init_db()
        with session_scope() as session:
            customer = session.execute(
                select(Customer).where(
                    Customer.tenant_id == int(tenant_id),
                    Customer.session_id == session_id,
                )
            ).scalars().first()
            if not customer:
                return False
            customer_id = customer.id
            channel_session_ids = session.execute(
                select(ChannelSession.id).where(
                    ChannelSession.tenant_id == int(tenant_id),
                    ChannelSession.session_key == session_id,
                )
            ).scalars().all()

            try:
                session.execute(
                    delete(StageLog).where(
                        StageLog.tenant_id == int(tenant_id),
                        StageLog.customer_id == customer_id,
                    )
                )
                session.execute(
                    delete(CustomerChatLog).where(
                        CustomerChatLog.tenant_id == int(tenant_id),
                        CustomerChatLog.customer_id == customer_id,
                    )
                )
                session.execute(
                    delete(CustomerChatArchive).where(
                        CustomerChatArchive.tenant_id == int(tenant_id),
                        CustomerChatArchive.customer_id == customer_id,
                    )
                )
                session.execute(
                    delete(BehaviorEvent).where(
                        BehaviorEvent.tenant_id == int(tenant_id),
                        BehaviorEvent.session_id == session_id,
                    )
                )
                session.execute(
                    delete(CustomerTag).where(
                        CustomerTag.tenant_id == int(tenant_id),
                        CustomerTag.customer_id == customer_id,
                    )
                )
                session.execute(
                    delete(Notification).where(
                        Notification.tenant_id == int(tenant_id),
                        Notification.customer_id == customer_id,
                    )
                )
                session.execute(
                    delete(FollowupTask).where(
                        FollowupTask.tenant_id == int(tenant_id),
                        FollowupTask.session_id == session_id,
                    )
                )
                if channel_session_ids:
                    session.execute(
                        delete(ChannelMessage).where(
                            ChannelMessage.tenant_id == int(tenant_id),
                            ChannelMessage.session_id.in_(channel_session_ids),
                        )
                    )
                    session.execute(
                        delete(ChannelSession).where(
                            ChannelSession.tenant_id == int(tenant_id),
                            ChannelSession.id.in_(channel_session_ids),
                        )
                    )
                # 泛化清理其余带 customer_id/session_id 的表，避免新增业务表后删除遗漏。
                known = {
                    "customers",
                    "stage_log",
                    "customer_chat_log",
                    "customer_chat_archive",
                    "behavior_events",
                    "customer_tags",
                    "notifications",
                    "followup_tasks",
                    "channel_messages",
                    "channel_sessions",
                }
                from core.models import Base

                for table in Base.metadata.sorted_tables:
                    table_name = table.name
                    if table_name in known:
                        continue
                    columns = {column.name for column in table.columns}
                    if "tenant_id" not in columns:
                        continue
                    if "customer_id" in columns:
                        session.execute(
                            table.delete().where(
                                table.c.tenant_id == int(tenant_id),
                                table.c.customer_id == customer_id,
                            )
                        )
                    if "session_id" in columns:
                        session.execute(
                            table.delete().where(
                                table.c.tenant_id == int(tenant_id),
                                table.c.session_id == session_id,
                            )
                        )
                session.delete(customer)
                session.flush()
            except Exception as exc:
                raise EraseIncomplete(str(exc)) from exc
        return True

    def compliance_status(
        self,
        session_id: str,
        tenant_id: int | None = None,
    ) -> dict:
        consents = self.list_consents(session_id, tenant_id=tenant_id)
        requests = self.list_deletion_requests(tenant_id=tenant_id)
        customer_requests = [r for r in requests if r["session_id"] == session_id]
        has_data = None
        try:
            from core.sales_crm import crm

            customer = crm.get_by_session(session_id, tenant_id=tenant_id)
            has_data = customer is not None
        except Exception as exc:
            logger.warning("查询客户是否仍有数据失败，本次不给出结论: %s", exc)
        return {
            "consents": consents,
            "deletion_requests": customer_requests,
            "has_data": has_data,
            "has_data_known": has_data is not None,
        }


compliance_flow = ComplianceFlow()
