"""隐私工具：PII 脱敏、数据分级和保留期清理。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from config.settings import settings
from core.db import session_scope
from core.models import CustomerChatArchive, CustomerChatLog


_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_WXID_RE = re.compile(r"\bwxid_[A-Za-z0-9_-]+\b", re.I)


def mask_pii(value) -> str:
    text = str(value or "")
    text = _PHONE_RE.sub(lambda m: m.group(1)[:3] + "****" + m.group(1)[-4:], text)
    text = _EMAIL_RE.sub(lambda m: m.group(1)[:2] + "***@" + m.group(2), text)
    text = _WXID_RE.sub("wxid_***", text)
    return text


def classify_field(name: str) -> str:
    key = str(name or "").lower()
    if any(token in key for token in ("password", "secret", "key", "token")):
        return "secret"
    if any(token in key for token in ("phone", "email", "wechat", "wxid", "payment", "content")):
        return "high"
    if any(token in key for token in ("customer", "lead", "order", "profile")):
        return "medium"
    return "low"


def retention_cutoff(days: int | None = None) -> str:
    value = int(days or settings.CHAT_RETENTION_DAYS or 180)
    return (datetime.now() - timedelta(days=max(value, 1))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def purge_expired_chat(
    tenant_id: int | None = None,
    days: int | None = None,
) -> dict:
    cutoff = retention_cutoff(days)
    with session_scope() as session:
        chat_query = delete(CustomerChatLog).where(
            CustomerChatLog.created_at < cutoff
        )
        archive_query = delete(CustomerChatArchive).where(
            CustomerChatArchive.created_at < cutoff
        )
        if tenant_id is not None:
            chat_query = chat_query.where(
                CustomerChatLog.tenant_id == int(tenant_id)
            )
            archive_query = archive_query.where(
                CustomerChatArchive.tenant_id == int(tenant_id)
            )
        chat_result = session.execute(chat_query)
        archive_result = session.execute(archive_query)
    return {
        "cutoff": cutoff,
        "removed_chat": int(chat_result.rowcount or 0),
        "removed_archive": int(archive_result.rowcount or 0),
    }


def privacy_status(tenant_id: int | None = None) -> dict:
    with session_scope(read_only=True) as session:
        chat_query = select(CustomerChatLog)
        archive_query = select(CustomerChatArchive)
        if tenant_id is not None:
            chat_query = chat_query.where(
                CustomerChatLog.tenant_id == int(tenant_id)
            )
            archive_query = archive_query.where(
                CustomerChatArchive.tenant_id == int(tenant_id)
            )
        chat_count = len(session.execute(chat_query).scalars().all())
        archive_count = len(session.execute(archive_query).scalars().all())
    return {
        "tenant_id": tenant_id,
        "chat_retention_days": int(settings.CHAT_RETENTION_DAYS or 180),
        "audit_retention_days": int(settings.AUDIT_RETENTION_DAYS or 180),
        "deletion_sla_days": int(settings.DELETION_SLA_DAYS or 15),
        "chat_records": chat_count,
        "archived_records": archive_count,
        "classification_enabled": bool(settings.DATA_CLASSIFICATION_ENABLED),
    }
