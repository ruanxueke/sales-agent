"""租户上下文工具：统一解析会话归属，避免后台任务丢失 tenant_id。"""
from __future__ import annotations

import re


_TENANT_SESSION_RE = re.compile(
    r"^(?:personal_wechat|official|wechat|wecom_kf|wecom|webchat):(\d+):"
)


def default_tenant_id() -> int:
    from core.security import default_tenant_id as _default

    return _default()


def tenant_from_session_id(session_id: str, default: int | None = None) -> int:
    """从统一会话键中解析租户，旧键无租户信息时回到默认租户。"""
    value = str(session_id or "").strip()
    match = _TENANT_SESSION_RE.match(value)
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            pass
    return default_tenant_id() if default is None else int(default)


def tenant_session_key(channel: str, tenant_id: int, external_id: str) -> str:
    channel = str(channel or "unknown").strip() or "unknown"
    external_id = str(external_id or "").strip()
    return f"{channel}:{int(tenant_id)}:{external_id}"


def with_tenant_prefix(namespace: str, tenant_id: int, key: str) -> str:
    return f"tenant:{int(tenant_id)}:{namespace}:{key}"
