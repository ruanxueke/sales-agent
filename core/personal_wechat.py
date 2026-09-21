"""个人微信桥接服务：统一会话入库、AI 回复任务与发送回执。"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import and_, inspect, or_, select, text
from core.db import engine

from core.audit import audit
from core.commercial import commercial
from core.db import init_db, session_scope
from core.idempotency import idempotency_store
from core.models import (
    ChannelSession,
    Customer,
    Lead,
    PersonalWechatBridgeInstance,
    PersonalWechatReplyTask,
)
from core.security import default_tenant_id

logger = logging.getLogger(__name__)

VALID_MODES = {"off", "draft", "auto", "manual"}
ACK_STATUSES = {
    "drafted",
    "sent",
    "failed",
    "skipped",
    "handover",
    "manual_review",
    "dead_letter",
}
RETRYABLE_FAILURE_CODES = {
    "RETRYABLE_UI",
    "WINDOW_FOCUS_LOST",
    "NETWORK_ERROR",
}
TASK_TTL_HOURS = 24
LEASE_SECONDS = 300
_local_generation_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _task_id() -> str:
    return f"pwt-{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}"


def _row_to_dict(row: PersonalWechatReplyTask) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(value or "", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


@contextmanager
def _generation_lock(session_key: str):
    """同一会话串行生成回复；有 Redis 时同时做跨进程锁。"""
    with _locks_guard:
        local_lock = _local_generation_locks.setdefault(session_key, threading.Lock())
    local_lock.acquire()
    redis_lock = None
    redis_acquired = False
    redis_key = f"personal_wechat:generation:{session_key}"
    try:
        from core.redis_session import get_sync_redis

        redis_lock = get_sync_redis()
        if redis_lock is not None:
            deadline = time.time() + 20
            while time.time() < deadline:
                if redis_lock.set(redis_key, "1", nx=True, ex=120):
                    redis_acquired = True
                    break
                time.sleep(0.05)
            if not redis_acquired:
                raise RuntimeError("同一会话回复生成锁等待超时")
        yield
    finally:
        if redis_acquired and redis_lock is not None:
            try:
                redis_lock.delete(redis_key)
            except Exception as e:
                logger.warning("释放微信生成锁失败，锁会保留到 TTL 到期: %s", e)
        local_lock.release()


class PersonalWechatService:
    def __init__(self):
        init_db()
        self._ensure_columns()

    @staticmethod
    def _ensure_columns() -> None:
        """为已存在的数据库补充新增设置字段。"""
        try:
            inspector = inspect(engine)
            table_name = "personal_wechat_bridge_instances"
            table_names = set(inspector.get_table_names())
            if table_name not in table_names:
                return
            columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            statements = []
            if "detect_wechat_login" not in columns:
                statements.append(
                    "ALTER TABLE personal_wechat_bridge_instances "
                    "ADD COLUMN detect_wechat_login BOOLEAN DEFAULT TRUE"
                )
            if "wechat_login_detected" not in columns:
                statements.append(
                    "ALTER TABLE personal_wechat_bridge_instances "
                    "ADD COLUMN wechat_login_detected BOOLEAN DEFAULT FALSE"
                )
            if "recognition_enabled" not in columns:
                statements.append(
                    "ALTER TABLE personal_wechat_bridge_instances "
                    "ADD COLUMN recognition_enabled BOOLEAN DEFAULT FALSE"
                )
            if statements:
                with engine.begin() as connection:
                    for statement in statements:
                        connection.execute(text(statement))

            task_table = "personal_wechat_reply_tasks"
            if task_table in table_names:
                task_columns = {
                    column["name"]
                    for column in inspector.get_columns(task_table)
                }
                task_columns_sql = {
                    "attempt_count": "INTEGER DEFAULT 0",
                    "max_attempts": "INTEGER DEFAULT 3",
                    "next_retry_at": "VARCHAR(32) DEFAULT ''",
                    "failure_code": "VARCHAR(64) DEFAULT ''",
                    "failure_stage": "VARCHAR(32) DEFAULT ''",
                    "send_token": "VARCHAR(64) DEFAULT ''",
                    "send_started_at": "VARCHAR(32) DEFAULT ''",
                    "send_confirmed_at": "VARCHAR(32) DEFAULT ''",
                    "manual_review_at": "VARCHAR(32) DEFAULT ''",
                    "diagnostic_path": "TEXT DEFAULT ''",
                }
                statements = [
                    f"ALTER TABLE {task_table} ADD COLUMN {name} {definition}"
                    for name, definition in task_columns_sql.items()
                    if name not in task_columns
                ]
                if statements:
                    with engine.begin() as connection:
                        for statement in statements:
                            connection.execute(text(statement))
        except Exception as exc:
            logger.warning("个人微信桥接字段迁移失败: %s", exc)

    @staticmethod
    def make_message_id(
        account_id: str,
        target_username: str,
        created_at: int | float | str,
        content: str,
    ) -> str:
        raw = f"{account_id}:{target_username}:{created_at}:{content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def session_key(tenant_id: int, account_id: str, target_username: str) -> str:
        return f"personal_wechat:{tenant_id}:{account_id}:{target_username}"

    @staticmethod
    def _resolve_instance(session, instance_id: str, tenant_id: int):
        """按 (租户, 实例号) 定位桥接实例行。

        instance_id 在库里是全局唯一，而各客户端的默认值可能相同。
        早期实现不带租户条件，导致 A 客户的心跳会覆盖 B 客户的实例行、
        A 控制台的「开始识别」会真的把 B 的桥接拉起来。
        这里必须严格按租户查，并显式拒绝跨租户占用。
        """
        row = session.execute(
            select(PersonalWechatBridgeInstance).where(
                PersonalWechatBridgeInstance.instance_id == instance_id,
                PersonalWechatBridgeInstance.tenant_id == tenant_id,
            )
        ).scalars().first()
        if row is not None:
            return row, ""
        taken = session.execute(
            select(PersonalWechatBridgeInstance).where(
                PersonalWechatBridgeInstance.instance_id == instance_id,
                PersonalWechatBridgeInstance.tenant_id != tenant_id,
            )
        ).scalars().first()
        if taken is not None:
            return None, f"实例号 {instance_id} 已被其他租户占用，请更换 instance_id"
        return None, ""

    def heartbeat(self, payload: dict, tenant_id: int | None = None) -> dict:
        instance_id = str(payload.get("instance_id") or "").strip()
        if not instance_id:
            return {"ok": False, "error": "instance_id 必填"}
        # 租户一律来自鉴权凭据（凭据即租户），不接受请求体自报的 tenant_id
        tid = int(tenant_id) if tenant_id is not None else default_tenant_id()
        with session_scope() as session:
            row, conflict = self._resolve_instance(session, instance_id, tid)
            if conflict:
                return {"ok": False, "error": conflict}
            if not row:
                row = PersonalWechatBridgeInstance(
                    instance_id=instance_id,
                    tenant_id=tid,
                )
                session.add(row)
            row.status = str(payload.get("status") or "online")[:24]
            row.account_id = str(payload.get("account_id") or "")[:128]
            row.mode = str(payload.get("mode") or "draft")[:16]
            row.auto_discover_contacts = bool(payload.get("auto_discover_contacts"))
            row.notify_on_message = bool(payload.get("notify_on_message", True))
            row.wechat_login_detected = bool(
                payload.get("wechat_login_detected", False)
            )
            row.poll_interval_seconds = max(
                1, int(payload.get("poll_interval_seconds") or 10)
            )
            row.last_message_at = str(payload.get("last_message_at") or "")
            row.last_reply_at = str(payload.get("last_reply_at") or "")
            row.last_error = str(payload.get("last_error") or "")[:1000]
            row.detail_json = json.dumps(
                payload.get("detail") or {},
                ensure_ascii=False,
            )
            row.last_seen = _now()
            row.updated_at = _now()
            session.flush()
            result = _row_to_dict(row)
        return {"ok": True, "instance": result}

    def update_settings(
        self,
        payload: dict,
        tenant_id: int | None = None,
    ) -> dict:
        instance_id = str(payload.get("instance_id") or "").strip()
        if not instance_id:
            return {"ok": False, "error": "instance_id 必填"}
        # 租户一律来自鉴权凭据（凭据即租户），不接受请求体自报的 tenant_id
        tid = int(tenant_id) if tenant_id is not None else default_tenant_id()
        with session_scope() as session:
            row, conflict = self._resolve_instance(session, instance_id, tid)
            if conflict:
                return {"ok": False, "error": conflict}
            if not row:
                row = PersonalWechatBridgeInstance(
                    instance_id=instance_id,
                    tenant_id=tid,
                )
                session.add(row)
            if "detect_wechat_login" in payload:
                row.detect_wechat_login = bool(payload["detect_wechat_login"])
            if "notify_on_message" in payload:
                row.notify_on_message = bool(payload["notify_on_message"])
            if "recognition_enabled" in payload:
                row.recognition_enabled = bool(payload["recognition_enabled"])
            row.updated_at = _now()
            row.last_seen = row.last_seen or _now()
            session.flush()
            result = _row_to_dict(row)
        return {"ok": True, "instance": result}

    def get_settings(
        self,
        instance_id: str,
        tenant_id: int | None = None,
    ) -> dict:
        instance_id = (instance_id or "").strip()
        if not instance_id:
            return {"ok": False, "error": "instance_id 必填"}
        with session_scope() as session:
            query = select(PersonalWechatBridgeInstance).where(
                PersonalWechatBridgeInstance.instance_id == instance_id
            )
            if tenant_id is not None:
                query = query.where(PersonalWechatBridgeInstance.tenant_id == tenant_id)
            row = session.execute(query).scalars().first()
            if not row:
                return {
                    "ok": True,
                    "settings": {
                        "instance_id": instance_id,
                        "recognition_enabled": False,
                        "detect_wechat_login": True,
                        "notify_on_message": True,
                    },
                }
            return {
                "ok": True,
                "settings": {
                    "instance_id": row.instance_id,
                    "recognition_enabled": bool(row.recognition_enabled),
                    "detect_wechat_login": bool(row.detect_wechat_login),
                    "notify_on_message": bool(row.notify_on_message),
                },
            }

    def status(
        self,
        tenant_id: int | None = None,
        instance_id: str = "",
    ) -> dict:
        from core.models import ChannelSession

        with session_scope(read_only=True) as session:
            query = select(PersonalWechatBridgeInstance).order_by(
                PersonalWechatBridgeInstance.last_seen.desc()
            )
            if instance_id:
                query = query.where(
                    PersonalWechatBridgeInstance.instance_id == instance_id
                )
            if tenant_id is not None:
                query = query.where(PersonalWechatBridgeInstance.tenant_id == tenant_id)
            instance = session.execute(query).scalars().first()

            task_query = select(PersonalWechatReplyTask)
            if tenant_id is not None:
                task_query = task_query.where(
                    PersonalWechatReplyTask.tenant_id == tenant_id
                )
            tasks = session.execute(
                task_query.order_by(PersonalWechatReplyTask.id.desc()).limit(500)
            ).scalars().all()

            session_query = select(ChannelSession).where(
                ChannelSession.channel == "personal_wechat"
            )
            if tenant_id is not None:
                session_query = session_query.where(ChannelSession.tenant_id == tenant_id)
            sessions = session.execute(
                session_query.order_by(ChannelSession.updated_at.desc()).limit(200)
            ).scalars().all()

        counts = {}
        for task in tasks:
            counts[task.status] = counts.get(task.status, 0) + 1
        detail = {}
        if instance:
            try:
                detail = json.loads(instance.detail_json or "{}")
            except (TypeError, ValueError):
                detail = {}
        online = False
        last_seen = instance.last_seen if instance else ""
        seen_at = _parse_dt(last_seen)
        # 桥接主动上报 offline 时立即判定离线，不再靠 90 秒心跳窗口等它自然过期
        stopped = bool(instance) and str(instance.status or "") in ("offline", "stopped")
        if seen_at and not stopped:
            online = (datetime.now() - seen_at).total_seconds() <= 90
        recent_tasks = [
            {
                "task_id": row.task_id,
                "target_name": row.target_name,
                "target_username": row.target_username,
                "content": row.content,
                "mode": row.mode,
                "status": row.status,
                "error": row.error,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in tasks[:20]
        ]
        return {
            "ok": True,
            "online": online,
            "instance": _row_to_dict(instance) if instance else None,
            "detail": detail,
            "task_counts": counts,
            "task_total": len(tasks),
            "recent_tasks": recent_tasks,
            "sessions": len(sessions),
            "updated_at": _now(),
        }

    def ingest_event(self, payload: dict, tenant_id: int | None = None) -> dict:
        """接收一条本地微信事件，落统一会话并创建回复任务。"""
        account_id = str(payload.get("account_id") or "").strip()
        target_type = str(payload.get("target_type") or "contact").strip().lower()
        target_name = str(payload.get("target_name") or "").strip()
        target_username = str(payload.get("target_username") or "").strip()
        sender_name = str(payload.get("sender_name") or "").strip()
        content = str(payload.get("content") or "").strip()
        mode = str(payload.get("mode") or "draft").strip().lower()
        created_at = payload.get("created_at") or int(datetime.now().timestamp())

        if target_type not in {"contact", "group"}:
            return {"ok": False, "error": "target_type 仅支持 contact 或 group"}
        if not account_id or not target_username or not content:
            return {"ok": False, "error": "account_id、target_username 和 content 必填"}
        if mode not in VALID_MODES:
            return {"ok": False, "error": f"不支持的 mode: {mode}"}
        if bool(payload.get("is_self")):
            return {"ok": True, "ignored": True, "reason": "self_message"}

        # 租户一律来自鉴权凭据（凭据即租户），不接受请求体自报的 tenant_id
        tid = int(tenant_id) if tenant_id is not None else default_tenant_id()
        source_message_id = str(payload.get("message_id") or "").strip()
        if not source_message_id:
            source_message_id = self.make_message_id(
                account_id,
                target_username,
                created_at,
                content,
            )
        dedupe_key = f"personal_wechat:{tid}:{account_id}:{source_message_id}"
        if not idempotency_store.mark(dedupe_key, "personal_wechat"):
            existing = self.find_by_source_message(tid, account_id, source_message_id)
            return {
                "ok": True,
                "deduped": True,
                "task_id": (existing or {}).get("task_id", ""),
                "status": (existing or {}).get("status", ""),
            }

        stable_session_key = self.session_key(tid, account_id, target_username)
        ingested = commercial.ingest_message(
            tenant_id=tid,
            channel="personal_wechat",
            external_id=target_username,
            content=content,
            direction="in",
            session_key=stable_session_key,
            nickname=target_name,
            source_page=account_id,
            msg_type=str(payload.get("msg_type") or "text"),
        )
        if not ingested.get("ok"):
            return ingested

        self.sync_contact_names(
            tenant_id=tid,
            account_id=account_id,
            contacts=[
                {
                    "target_username": target_username,
                    "target_name": target_name,
                }
            ],
        )

        session_id = (ingested.get("session") or {}).get("id")
        if mode == "off":
            audit(
                actor=f"personal-wechat:{account_id}",
                action="personal_wechat_ignored",
                resource=stable_session_key,
                detail=f"mode=off; sender={sender_name}",
                category="channel",
            )
            return {
                "ok": True,
                "ignored": True,
                "reason": "mode_off",
                "session_id": session_id,
            }

        with session_scope() as session:
            row = PersonalWechatReplyTask(
                task_id=_task_id(),
                tenant_id=tid,
                source_message_id=source_message_id,
                account_id=account_id,
                session_id=session_id,
                target_type=target_type,
                target_name=target_name,
                target_username=target_username,
                content="",
                mode=mode,
                status="generating" if mode in {"draft", "auto"} else "manual",
                send_token=uuid.uuid4().hex,
                expires_at=(datetime.now() + timedelta(hours=TASK_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S"),
            )
            session.add(row)
            session.flush()
            result = _row_to_dict(row)

        audit(
            actor=f"personal-wechat:{account_id}",
            action="personal_wechat_event",
            resource=stable_session_key,
            detail=f"message_id={source_message_id}; mode={mode}; task_id={result['task_id']}",
            category="channel",
        )
        return {
            "ok": True,
            "deduped": bool(ingested.get("deduped")),
            "session_id": session_id,
            "task_id": result["task_id"],
            "status": result["status"],
        }

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
    def _unique_display_id(session, model, desired: str, current_id: int) -> str:
        desired = str(desired or "").strip()
        if not desired:
            return ""
        used = {
            str(value or "")
            for value in session.execute(
                select(model.display_id).where(
                    model.id != current_id,
                    model.display_id != "",
                )
            ).scalars().all()
        }
        if desired not in used:
            return desired
        index = 2
        while f"{desired}{index}" in used:
            index += 1
        return f"{desired}{index}"

    def sync_contact_names(
        self,
        tenant_id: int | None,
        account_id: str,
        contacts: list[dict],
    ) -> dict:
        """按稳定 wxid 将客户展示名统一为微信备注名。"""
        account_id = str(account_id or "").strip()
        if not account_id:
            return {"ok": False, "error": "account_id 必填"}
        canonical_by_username: dict[str, str] = {}
        for item in contacts or []:
            username = str(item.get("target_username") or "").strip()
            name = str(item.get("target_name") or "").strip()
            if username and name:
                canonical_by_username[username] = name
        if not canonical_by_username:
            return {"ok": True, "updated": 0}

        tid = int(tenant_id or 0)
        counts = {
            "sessions": 0,
            "leads": 0,
            "customers": 0,
            "tasks": 0,
        }
        with session_scope() as session:
            for target_username, canonical_name in canonical_by_username.items():
                stable_session_key = self.session_key(tid, account_id, target_username)
                channel_session = session.execute(
                    select(ChannelSession).where(
                        ChannelSession.tenant_id == tid,
                        ChannelSession.channel == "personal_wechat",
                        or_(
                            ChannelSession.external_id == target_username,
                            ChannelSession.session_key == stable_session_key,
                        ),
                    )
                ).scalars().first()
                lead = session.execute(
                    select(Lead).where(
                        Lead.tenant_id == tid,
                        Lead.session_id == stable_session_key,
                    )
                ).scalars().first()
                customer = session.execute(
                    select(Customer).where(
                        Customer.session_id == stable_session_key,
                    )
                ).scalars().first()

                if channel_session:
                    if channel_session.nickname != canonical_name:
                        channel_session.nickname = canonical_name
                        channel_session.updated_at = _now()
                        counts["sessions"] += 1
                    if lead and not channel_session.lead_id:
                        channel_session.lead_id = lead.id
                    if customer and not channel_session.customer_id:
                        channel_session.customer_id = customer.id

                for entity, count_key in ((lead, "leads"), (customer, "customers")):
                    if not entity:
                        continue
                    old_name = str(entity.nickname or "").strip()
                    if old_name != canonical_name:
                        entity.nickname = canonical_name
                        entity.updated_at = _now()
                        counts[count_key] += 1
                    if self._display_id_follows_name(entity.display_id, old_name):
                        entity.display_id = self._unique_display_id(
                            session,
                            type(entity),
                            canonical_name,
                            entity.id,
                        )

                tasks = session.execute(
                    select(PersonalWechatReplyTask).where(
                        PersonalWechatReplyTask.tenant_id == tid,
                        PersonalWechatReplyTask.account_id == account_id,
                        PersonalWechatReplyTask.target_username == target_username,
                    )
                ).scalars().all()
                for task in tasks:
                    if task.target_name != canonical_name:
                        task.target_name = canonical_name
                        task.updated_at = _now()
                        counts["tasks"] += 1

        if any(counts.values()):
            audit(
                actor=f"personal-wechat:{account_id}",
                action="personal_wechat_contact_names_synced",
                resource=account_id,
                detail=json.dumps(counts, ensure_ascii=False),
                category="channel",
            )
        return {"ok": True, "updated": sum(counts.values()), "counts": counts}

    def find_by_source_message(self, tenant_id: int, account_id: str, source_message_id: str) -> dict | None:
        with session_scope(read_only=True) as session:
            row = session.execute(
                select(PersonalWechatReplyTask).where(
                    PersonalWechatReplyTask.tenant_id == tenant_id,
                    PersonalWechatReplyTask.account_id == account_id,
                    PersonalWechatReplyTask.source_message_id == source_message_id,
                )
            ).scalars().first()
            return _row_to_dict(row) if row else None

    def generate_task(self, task_id: str) -> dict:
        with session_scope(read_only=True) as session:
            row = session.execute(
                select(PersonalWechatReplyTask).where(
                    PersonalWechatReplyTask.task_id == task_id,
                )
            ).scalars().first()
            if not row:
                return {"ok": False, "error": "任务不存在"}
            stable_session_key = self.session_key(
                int(row.tenant_id or 0),
                row.account_id or "",
                row.target_username or "",
            )
        with _generation_lock(stable_session_key):
            return self._generate_task_locked(task_id)

    def _generate_task_locked(self, task_id: str) -> dict:
        """调用销售 Agent，生成待本地发送的回复。"""
        with session_scope() as session:
            row = session.execute(
                select(PersonalWechatReplyTask).where(
                    PersonalWechatReplyTask.task_id == task_id,
                )
            ).scalars().first()
            if not row:
                return {"ok": False, "error": "任务不存在"}
            if row.status != "generating":
                return {"ok": True, "skipped": True, "status": row.status}
            task = _row_to_dict(row)

        source = "personal_wechat"
        stable_session_key = self.session_key(
            int(task.get("tenant_id") or 0),
            task.get("account_id") or "",
            task.get("target_username") or "",
        )
        try:
            from core.agent import sales_agent

            inbound = self._latest_inbound_content(task)
            reply = ""
            last_validation_error = None
            for _ in range(2):
                candidate = sales_agent.chat(
                    inbound,
                    session_id=stable_session_key,
                    nickname=task.get("target_name") or "",
                    source=source,
                )
                try:
                    reply = self._validate_reply(candidate)
                    break
                except RuntimeError as exc:
                    last_validation_error = exc
            if not reply:
                raise RuntimeError(
                    f"GENERATION_VALIDATION_FAILED: {last_validation_error}"
                )

            commercial.ingest_message(
                tenant_id=int(task.get("tenant_id") or 0),
                channel=source,
                external_id=task.get("target_username") or "",
                content=reply,
                direction="out",
                session_key=stable_session_key,
                nickname=task.get("target_name") or "",
                source_page=task.get("account_id") or "",
                msg_type="text",
            )
        except Exception as exc:
            logger.exception("个人微信回复生成失败 task_id=%s", task_id)
            with session_scope() as session:
                row = session.execute(
                    select(PersonalWechatReplyTask).where(
                        PersonalWechatReplyTask.task_id == task_id,
                    )
                ).scalars().first()
                if row:
                    row.status = "failed"
                    row.error = str(exc)[:500]
                    row.failure_code = "GENERATION_FAILED"
                    row.failure_stage = "generation"
                    row.updated_at = _now()
            return {"ok": False, "task_id": task_id, "error": str(exc)[:500]}

        with session_scope() as session:
            row = session.execute(
                select(PersonalWechatReplyTask).where(
                    PersonalWechatReplyTask.task_id == task_id,
                )
            ).scalars().first()
            if not row:
                return {"ok": False, "error": "任务不存在"}
            if row.status != "generating":
                return {"ok": True, "skipped": True, "status": row.status}
            row.content = reply
            row.status = "pending"
            row.updated_at = _now()
            result = _row_to_dict(row)
        audit(
            actor=f"personal-wechat:{task.get('account_id') or ''}",
            action="personal_wechat_reply_generated",
            resource=stable_session_key,
            detail=f"task_id={task_id}",
            category="ai",
        )
        return {"ok": True, "task": result}

    def _latest_inbound_content(self, task: dict) -> str:
        from core.models import ChannelMessage

        with session_scope(read_only=True) as session:
            row = session.execute(
                select(ChannelMessage).where(
                    ChannelMessage.tenant_id == int(task.get("tenant_id") or 0),
                    ChannelMessage.session_id == int(task.get("session_id") or 0),
                    ChannelMessage.direction == "in",
                ).order_by(ChannelMessage.id.desc())
            ).scalars().first()
            return row.content if row else ""

    @staticmethod
    def _validate_reply(reply: str) -> str:
        text = str(reply or "").strip()
        if len(text) < 2:
            raise RuntimeError("EMPTY_REPLY")
        if len(text) > 2000:
            raise RuntimeError("REPLY_TOO_LONG")
        lowered = text.lower()
        forbidden = (
            "system prompt",
            "api key",
            "apikey",
            "sk-",
            "access token",
            "系统提示词",
            "接口密钥",
        )
        if any(item in lowered for item in forbidden):
            raise RuntimeError("SENSITIVE_REPLY_BLOCKED")
        return text

    def metrics(
        self,
        tenant_id: int | None = None,
        account_id: str = "",
    ) -> dict:
        with session_scope(read_only=True) as session:
            query = select(PersonalWechatReplyTask)
            if tenant_id is not None:
                query = query.where(PersonalWechatReplyTask.tenant_id == tenant_id)
            if account_id:
                query = query.where(PersonalWechatReplyTask.account_id == account_id)
            rows = session.execute(query).scalars().all()
        status_counts: dict[str, int] = {}
        failure_counts: dict[str, int] = {}
        retrying = 0
        manual_review = 0
        for row in rows:
            status = str(row.status or "")
            status_counts[status] = status_counts.get(status, 0) + 1
            if row.failure_code:
                code = str(row.failure_code)
                failure_counts[code] = failure_counts.get(code, 0) + 1
            if status == "pending" and row.next_retry_at:
                retrying += 1
            if status == "manual_review":
                manual_review += 1
        total = len(rows)
        sent = status_counts.get("sent", 0)
        return {
            "ok": True,
            "total": total,
            "status_counts": status_counts,
            "failure_counts": failure_counts,
            "retrying": retrying,
            "manual_review": manual_review,
            "send_success_rate": round(sent / total, 4) if total else 1.0,
        }

    def claim_tasks(
        self,
        tenant_id: int | None,
        account_id: str,
        limit: int = 20,
        claimed_by: str = "",
    ) -> list[dict]:
        account_id = (account_id or "").strip()
        if not account_id:
            return []
        now = datetime.now()
        now_text = now.strftime("%Y-%m-%d %H:%M:%S")
        lease_text = (now + timedelta(seconds=LEASE_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")
        claimed: list[dict] = []
        with session_scope() as session:
            query = (
                select(PersonalWechatReplyTask)
                .where(
                    PersonalWechatReplyTask.account_id == account_id,
                    PersonalWechatReplyTask.status.in_(("pending", "claimed")),
                    or_(
                        and_(
                            PersonalWechatReplyTask.status == "pending",
                            or_(
                                PersonalWechatReplyTask.next_retry_at == "",
                                PersonalWechatReplyTask.next_retry_at <= now_text,
                            ),
                        ),
                        and_(
                            PersonalWechatReplyTask.status == "claimed",
                            PersonalWechatReplyTask.lease_expires_at < now_text,
                        ),
                    ),
                )
                .order_by(
                    PersonalWechatReplyTask.created_at.asc(),
                    PersonalWechatReplyTask.id.asc(),
                )
                .limit(max(1, min(int(limit or 20), 100)))
                .with_for_update(skip_locked=True)
            )
            if tenant_id is not None:
                query = query.where(PersonalWechatReplyTask.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
            for row in rows:
                expires = _parse_dt(row.expires_at)
                if expires and expires < now:
                    row.status = "expired"
                    row.updated_at = now_text
                    continue
                row.status = "claimed"
                row.claimed_by = claimed_by or account_id
                row.claimed_at = now_text
                row.lease_expires_at = lease_text
                row.updated_at = now_text
                claimed.append(_row_to_dict(row))
        for item in claimed:
            audit(
                actor=f"personal-wechat:{claimed_by or account_id}",
                action="personal_wechat_task_claimed",
                resource=item.get("task_id") or "",
                category="channel",
            )
        return claimed

    def list_pending_tasks(
        self,
        tenant_id: int | None,
        account_id: str,
        limit: int = 20,
    ) -> list[dict]:
        account_id = (account_id or "").strip()
        if not account_id:
            return []
        with session_scope(read_only=True) as session:
            query = (
                select(PersonalWechatReplyTask)
                .where(
                    PersonalWechatReplyTask.account_id == account_id,
                    PersonalWechatReplyTask.status == "pending",
                )
                .order_by(
                    PersonalWechatReplyTask.created_at.asc(),
                    PersonalWechatReplyTask.id.asc(),
                )
                .limit(max(1, min(int(limit or 20), 100)))
            )
            if tenant_id is not None:
                query = query.where(PersonalWechatReplyTask.tenant_id == tenant_id)
            rows = session.execute(query).scalars().all()
            return [_row_to_dict(row) for row in rows]

    def ack_task(
        self,
        task_id: str,
        status: str,
        tenant_id: int | None = None,
        error: str = "",
        sent_at: str = "",
        failure_code: str = "",
        failure_stage: str = "",
        diagnostic_path: str = "",
    ) -> dict:
        status = (status or "").strip().lower()
        if status not in ACK_STATUSES:
            return {"ok": False, "error": f"不支持的 status: {status}"}
        with session_scope() as session:
            query = select(PersonalWechatReplyTask).where(
                PersonalWechatReplyTask.task_id == task_id,
            )
            if tenant_id is not None:
                query = query.where(PersonalWechatReplyTask.tenant_id == tenant_id)
            row = session.execute(query).scalars().first()
            if not row:
                return {"ok": False, "error": "任务不存在"}
            now = datetime.now()
            now_text = now.strftime("%Y-%m-%d %H:%M:%S")
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.failure_code = (failure_code or "")[:64]
            row.failure_stage = (failure_stage or "")[:32]
            row.diagnostic_path = diagnostic_path or ""
            retryable = (
                status == "failed"
                and row.failure_code in RETRYABLE_FAILURE_CODES
                and row.attempt_count < int(row.max_attempts or 3)
            )
            if retryable:
                delay_seconds = min(300, 5 * (2 ** max(0, row.attempt_count - 1)))
                row.status = "pending"
                row.next_retry_at = (
                    now + timedelta(seconds=delay_seconds)
                ).strftime("%Y-%m-%d %H:%M:%S")
                row.claimed_by = ""
                row.claimed_at = ""
                row.lease_expires_at = ""
            elif status == "failed" and row.failure_code not in RETRYABLE_FAILURE_CODES:
                row.status = "manual_review"
                row.manual_review_at = now_text
            else:
                row.status = status
                row.next_retry_at = ""
            row.error = (error or "")[:500]
            row.ack_at = sent_at or now_text
            if status == "sent":
                row.send_confirmed_at = sent_at or now_text
            row.updated_at = now_text
            result = _row_to_dict(row)
        audit(
            actor=f"personal-wechat:{row.claimed_by or row.account_id}",
            action="personal_wechat_task_ack",
            resource=task_id,
            detail=f"status={status}; error={(error or '')[:200]}",
            category="channel",
        )
        if result.get("status") in {"manual_review", "dead_letter"}:
            audit(
                actor=f"personal-wechat:{row.account_id or ''}",
                action="personal_wechat_alert",
                resource=task_id,
                detail=(
                    f"status={result.get('status')}; "
                    f"failure_code={result.get('failure_code') or ''}"
                ),
                category="channel",
            )
        return {"ok": True, "task": result}

    def retry_task(
        self,
        task_id: str,
        tenant_id: int | None = None,
    ) -> dict:
        with session_scope() as session:
            query = select(PersonalWechatReplyTask).where(
                PersonalWechatReplyTask.task_id == task_id,
            )
            if tenant_id is not None:
                query = query.where(PersonalWechatReplyTask.tenant_id == tenant_id)
            row = session.execute(query).scalars().first()
            if not row:
                return {"ok": False, "error": "task not found"}
            row.status = "pending"
            row.next_retry_at = ""
            row.claimed_by = ""
            row.claimed_at = ""
            row.lease_expires_at = ""
            row.failure_code = ""
            row.failure_stage = ""
            row.manual_review_at = ""
            row.error = ""
            row.updated_at = _now()
            result = _row_to_dict(row)
        audit(
            actor=f"personal-wechat:{row.account_id or ''}",
            action="personal_wechat_task_retry",
            resource=task_id,
            detail="manual retry",
            category="channel",
        )
        return {"ok": True, "task": result}


personal_wechat_service = PersonalWechatService()
