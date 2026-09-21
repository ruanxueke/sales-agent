"""租户数据过滤辅助：统一按 tenant_id 过滤列表数据

语义约定（重要）：
1. tenant_id 为 None → 超级管理员视角，返回全部；
2. 表本身没有租户维度（模型里没有 tenant_id 字段）→ 不属于租户数据，原样返回。
   项目 79 个模型里有 65 个没有租户列（话术库、产品知识、工单、审计等），
   它们本来就不是按租户隔离的，不能因为传入了租户号就被过滤成空列表；
3. 有租户列但值为 NULL 的历史数据（租户列是后加的）→ 归默认租户，
   避免升级后老数据在所有租户下都消失。
"""
from __future__ import annotations

_MISSING = object()


def _default_tenant_id() -> int:
    try:
        from config.settings import settings
        return int(getattr(settings, "DEFAULT_TENANT_ID", 0) or 0)
    except Exception:
        return 0


def _read(item, key: str):
    """读取租户字段；字段不存在返回 _MISSING。"""
    if isinstance(item, dict):
        return item[key] if key in item else _MISSING
    try:
        if hasattr(item, key):
            return getattr(item, key)
    except Exception:
        return _MISSING
    return _MISSING


def filter_by_tenant(items, tenant_id, key: str = "tenant_id"):
    """按租户过滤列表。

    tenant_id 为 None 时返回全部；表无租户维度时原样返回；其余只返回本租户数据。
    """
    if tenant_id is None:
        return items

    default_tid = _default_tenant_id()
    out = []
    for item in items or []:
        value = _read(item, key)
        if value is _MISSING:
            # 该表没有租户维度：不参与租户隔离
            out.append(item)
        elif value == tenant_id:
            out.append(item)
        elif value is None and tenant_id == default_tid:
            # 租户列新增之前写下的历史数据，归属默认租户
            out.append(item)
    return out
