"""RBAC 与服务账号：权限判断和数据库 API Key 生命周期。"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime

from sqlalchemy import select

from config.settings import settings
from core.db import session_scope
from core.models import ApiKeyAccount


ROLE_PERMISSIONS = {
    "super_admin": {"*"},
    "owner": {"*"},
    "admin": {"*"},
    "manager": {
        "customer:read",
        "customer:write",
        "lead:read",
        "lead:write",
        "order:read",
        "order:write",
        "report:read",
        "followup:read",
        "followup:write",
        "team:read",
        "knowledge:read",
        "knowledge:write",
        "data:export",
        "ticket:read",
        "ticket:write",
    },
    "sales": {
        "customer:read",
        "customer:write",
        "lead:read",
        "lead:write",
        "order:read",
        "followup:read",
        "chat:read",
        "chat:write",
        "knowledge:read",
    },
    "service": {
        "api:access",
        "customer:read",
        "ticket:read",
        "ticket:write",
        "order:read",
        "chat:read",
        "chat:write",
    },
    "api_service": {"api:access"},
    "finance": {
        "order:read",
        "finance:read",
        "finance:write",
        "report:read",
        "knowledge:read",
    },
    "viewer": {
        "customer:read",
        "lead:read",
        "report:read",
    },
}

DEFAULT_API_KEY_SCOPES = {
    "api:access",
    "customer:read",
    "lead:read",
    "channel:bridge",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_role(role: str) -> str:
    value = str(role or "api_service").strip().lower()
    return value if value in ROLE_PERMISSIONS else "api_service"


def permissions_for(role: str, scopes: list[str] | None = None) -> set[str]:
    base = set(ROLE_PERMISSIONS.get(normalize_role(role), set()))
    base.update(str(scope).strip() for scope in (scopes or []) if str(scope).strip())
    return base


def has_permission(role: str, required: str, scopes: list[str] | None = None) -> bool:
    perms = permissions_for(role, scopes)
    if "*" in perms or required in perms:
        return True
    resource = required.split(":", 1)[0]
    return f"{resource}:*" in perms


def required_permission_for_request(path: str, method: str = "GET") -> str:
    """按接口路径给出最低权限要求；空字符串表示仅要求已鉴权。"""
    path = str(path or "")
    method = str(method or "GET").upper()
    write = method in {"POST", "PUT", "PATCH", "DELETE"}
    if path == "/api/v1/accounts/me":
        return ""
    if path.startswith(("/api/v1/customer", "/api/v1/notifications")):
        return "customer:write" if write else "customer:read"
    if path.startswith("/api/v1/leads"):
        return "lead:write" if write else "lead:read"
    if path.startswith(("/api/v1/orders", "/api/v1/after-sales")):
        return "order:write" if write else "order:read"
    if path.startswith(
        (
            "/api/v1/opportunities",
            "/api/v1/quotes",
            "/api/v1/contracts",
            "/api/v1/cpq",
        )
    ):
        return "order:write" if write else "order:read"
    if path.startswith(("/api/v1/finance", "/api/v1/receivables")):
        return "finance:write" if write else "finance:read"
    if path.startswith("/api/v1/reports"):
        return "report:read"
    if path.startswith("/api/v1/export"):
        return "data:export"
    if path.startswith("/api/v1/knowledge"):
        return "knowledge:write" if write else "knowledge:read"
    if path.startswith(("/api/v1/ammo", "/api/v1/winning")):
        return "knowledge:read"
    if path.startswith("/api/v1/followups"):
        return "followup:write" if write else "followup:read"
    if path.startswith(("/api/v1/tickets", "/api/v1/handover", "/api/v1/quality")):
        return "ticket:write" if write else "ticket:read"
    if path.startswith("/api/v1/compliance"):
        return "admin:access"
    if path.startswith("/api/v1/personal-wechat"):
        return "channel:bridge"
    if path.startswith(
        (
            "/api/v1/accounts",
            "/api/v1/audit",
            "/api/v1/system",
            "/api/v1/platform",
            "/api/v1/tenant",
            "/api/v1/license",
            "/api/v1/billing",
        )
    ):
        return "admin:access"
    return ""


def hash_api_key(key: str) -> str:
    pepper = str(getattr(settings, "SECRET_KEY", "") or "")
    return hashlib.sha256(f"{pepper}\0{key}".encode("utf-8")).hexdigest()


def _decode_scopes(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    except (TypeError, ValueError):
        pass
    return []


def authenticate_service_key(key: str) -> dict | None:
    if not key:
        return None
    digest = hash_api_key(key)
    with session_scope() as session:
        row = session.execute(
            select(ApiKeyAccount).where(
                ApiKeyAccount.key_hash == digest,
                ApiKeyAccount.status == "active",
            )
        ).scalars().first()
        if not row:
            return None
        now = _now()
        if row.expires_at and row.expires_at <= now:
            return None
        row.last_used_at = now
        result = {
            "id": row.id,
            "tenant_id": int(row.tenant_id or 0),
            "name": row.name or "",
            "role": normalize_role(row.role),
            "scopes": _decode_scopes(row.scopes_json),
        }
        session.flush()
    return result


def create_service_key(
    *,
    tenant_id: int,
    name: str,
    role: str = "api_service",
    scopes: list[str] | None = None,
    expires_at: str = "",
    created_by: str = "",
) -> dict:
    raw_key = "sak_" + secrets.token_urlsafe(32)
    with session_scope() as session:
        row = ApiKeyAccount(
            tenant_id=int(tenant_id),
            name=str(name or "").strip(),
            key_hash=hash_api_key(raw_key),
            role=normalize_role(role),
            scopes_json=json.dumps(
                [str(item).strip() for item in (scopes or []) if str(item).strip()],
                ensure_ascii=False,
            ),
            status="active",
            expires_at=str(expires_at or ""),
            created_by=str(created_by or ""),
            created_at=_now(),
        )
        session.add(row)
        session.flush()
        result = {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "name": row.name,
            "role": row.role,
            "scopes": _decode_scopes(row.scopes_json),
            "expires_at": row.expires_at,
            "key": raw_key,
        }
    return result


def list_service_keys(tenant_id: int) -> list[dict]:
    with session_scope(read_only=True) as session:
        rows = session.execute(
            select(ApiKeyAccount)
            .where(ApiKeyAccount.tenant_id == int(tenant_id))
            .order_by(ApiKeyAccount.id.desc())
        ).scalars().all()
        return [
            {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "name": row.name,
                "role": row.role,
                "scopes": _decode_scopes(row.scopes_json),
                "status": row.status,
                "expires_at": row.expires_at,
                "last_used_at": row.last_used_at,
                "created_by": row.created_by,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def revoke_service_key(key_id: int, tenant_id: int) -> bool:
    with session_scope() as session:
        row = session.execute(
            select(ApiKeyAccount).where(
                ApiKeyAccount.id == int(key_id),
                ApiKeyAccount.tenant_id == int(tenant_id),
            )
        ).scalars().first()
        if not row:
            return False
        row.status = "revoked"
        session.flush()
        return True
