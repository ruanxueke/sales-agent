"""客户成功体系：租户健康度、续费预警、CSM 视图"""
from __future__ import annotations
from datetime import datetime

from sqlalchemy import text

from core.db import session_scope


def _parse(ts: str):
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _count(session, sql: str, params: dict | None = None):
    try:
        return int(session.execute(text(sql), params or {}).scalar() or 0)
    except Exception:
        return 0


def tenant_health(tenant_id: int | None = None) -> dict:
    """计算客户成功健康度 0-100。

    客户档案当前未按租户拆分，因此客户数/成交率/聊天量为全局指标；
    线索、订单等已带 tenant_id 的表按租户统计，缺失时自动降级为 0。
    """
    score = 50.0
    reasons = []
    params = {"tid": tenant_id or 0}
    with session_scope(read_only=True) as s:
        customers = _count(s, "SELECT COUNT(*) FROM customers")
        won = _count(s, "SELECT COUNT(*) FROM customers WHERE stage IN ('won','enrolled')")
        leads = _count(s, "SELECT COUNT(*) FROM leads WHERE tenant_id=:tid", params)
        orders = _count(s, "SELECT COUNT(*) FROM orders WHERE tenant_id=:tid", params)
        chat = _count(s, "SELECT COUNT(*) FROM customer_chat_log")
        bad = _count(s, "SELECT COUNT(*) FROM conversation_feedback WHERE rating='bad'")
    if customers > 0:
        win_rate = won / customers
        score += min(20, win_rate * 40)
    score += min(10, chat / 10)
    score += min(10, orders * 5)
    score -= min(20, bad * 10)
    if bad > 0:
        reasons.append(f"差评 {bad} 条，需跟进复盘")
    if customers == 0:
        reasons.append("暂无客户，需引导使用")
    if leads > 0 and orders == 0:
        reasons.append("有线索无成交，关注转化")
    if orders == 0 and customers > 0:
        reasons.append("有客户无成交，关注转化")
    return {
        "tenant_id": tenant_id,
        "health_score": round(max(0, min(100, score)), 1),
        "customers": customers,
        "won": won,
        "leads": leads,
        "orders": orders,
        "chats": chat,
        "bad_feedback": bad,
        "reasons": reasons,
    }


def renewal_alerts() -> list[dict]:
    """续费预警：订阅 30/7 天内到期（数据源与计费模块保持一致）"""
    from core.billing import billing
    from core.tenant import tenant_manager

    alerts = []
    for t in tenant_manager.list_tenants():
        sub = billing.get_subscription(t["id"])
        if not sub or sub.get("status") != "active":
            continue
        exp = _parse(sub.get("expires_at") or "")
        if not exp:
            continue
        days = (exp - datetime.now()).days
        if 0 <= days <= 7:
            level = "urgent"
        elif 7 < days <= 30:
            level = "warning"
        else:
            continue
        alerts.append({
            "tenant_id": t["id"],
            "tenant_name": t.get("name") or "",
            "plan": sub.get("plan"),
            "expires_at": sub.get("expires_at"),
            "days_left": days,
            "level": level,
        })
    alerts.sort(key=lambda x: x["days_left"])
    return alerts


def csm_overview() -> dict:
    """CSM 视图：租户列表 + 健康度 + 订阅 + 续费预警"""
    from core.billing import billing
    from core.tenant import tenant_manager

    tenants = tenant_manager.list_tenants()
    items = []
    for t in tenants:
        health = tenant_health(t["id"])
        sub = billing.get_subscription(t["id"])
        items.append({
            "tenant": t,
            "health": health,
            "subscription": sub,
        })
    return {"items": items, "renewal_alerts": renewal_alerts(), "total": len(items)}
