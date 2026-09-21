"""销售报表：转化漏斗、跟进提醒、数据看板"""
from __future__ import annotations
from datetime import datetime, timedelta

from core.sales_constants import STAGE_LABELS, STAGES
from core.sales_crm import crm


def _customers(tenant_id: int | None = None) -> list[dict]:
    return crm.list_customers(tenant_id=tenant_id)


def _stage_rank(stage: str) -> int:
    return STAGES.index(stage) if stage in STAGES else 0


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def conversion(days: int = 30, tenant_id: int | None = None):
    customers = _customers(tenant_id)
    total = len(customers)
    stage_counts = {s: 0 for s in STAGES}
    l3_plus = 0
    daily = {}
    cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    for c in customers:
        stage = c.get("stage") or "new"
        if stage in stage_counts:
            stage_counts[stage] += 1
        if _stage_rank(stage) >= _stage_rank("recommended"):
            l3_plus += 1
        created = (c.get("created_at") or "")[:10]
        if created >= cutoff:
            daily[created] = daily.get(created, 0) + 1

    high_intent = stage_counts["high_intent"]
    enrolled = stage_counts["enrolled"]
    won = stage_counts["won"]

    funnel = [
        {"stage": "new", "label": STAGE_LABELS["new"], "count": stage_counts["new"], "ratio": _rate(stage_counts["new"], total)},
        {"stage": "recommended", "label": "意向明确 L3+", "count": l3_plus, "ratio": _rate(l3_plus, total)},
        {"stage": "high_intent", "label": STAGE_LABELS["high_intent"], "count": high_intent, "ratio": _rate(high_intent, total)},
        {"stage": "enrolled", "label": STAGE_LABELS["enrolled"], "count": enrolled, "ratio": _rate(enrolled, total)},
        {"stage": "won", "label": STAGE_LABELS["won"], "count": won, "ratio": _rate(won, total)},
    ]
    rates = {
        "l3_rate": _rate(l3_plus, total),
        "high_intent_rate": _rate(high_intent, l3_plus),
        "enrolled_rate": _rate(enrolled, l3_plus),
        "won_rate": _rate(won, enrolled),
    }
    return {
        "total_customers": total,
        "funnel": funnel,
        "rates": rates,
        "daily_new": [{"date": d, "count": daily[d]} for d in sorted(daily)],
    }


def followups(limit: int = 200, tenant_id: int | None = None):
    now = datetime.now()
    rows = []
    for c in _customers(tenant_id):
        stage = c.get("stage") or "new"
        if _stage_rank(stage) < _stage_rank("recommended"):
            continue
        nf = c.get("next_follow_up") or ""
        if nf:
            try:
                due = datetime.strptime(nf, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                due = None
            if due is None:
                status = "待安排"
            elif due < now - timedelta(hours=1):
                status = "已逾期"
            elif due <= now:
                status = "到期"
            elif due <= now + timedelta(hours=24):
                status = "即将到期"
            else:
                status = "跟进中"
        else:
            status = "待安排"
        rows.append({
            "session_id": c.get("session_id"),
            "nickname": c.get("nickname") or "",
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, stage),
            "intent_level": c.get("intent_level") or "",
            "goal": c.get("goal") or "",
            "updated_at": c.get("updated_at") or "",
            "next_follow_up": nf,
            "status": status,
        })
    order = {"已逾期": 0, "到期": 1, "即将到期": 2, "跟进中": 3, "待安排": 4}
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["updated_at"] or ""))
    summary = {s: sum(1 for r in rows if r["status"] == s) for s in ("已逾期", "到期", "即将到期", "跟进中", "待安排")}
    return {"summary": summary, "followups": rows[:limit]}


def dashboard(days: int = 7, tenant_id: int | None = None):
    customers = _customers(tenant_id)
    total = len(customers)
    stage_counts = {s: 0 for s in STAGES}
    l3_plus = 0
    daily = {}
    cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    for c in customers:
        stage = c.get("stage") or "new"
        if stage in stage_counts:
            stage_counts[stage] += 1
        if _stage_rank(stage) >= _stage_rank("recommended"):
            l3_plus += 1
        created = (c.get("created_at") or "")[:10]
        if created >= cutoff:
            daily[created] = daily.get(created, 0) + 1

    try:
        today_messages = crm.count_today_messages(tenant_id=tenant_id)
    except Exception:
        today_messages = 0

    from core.usage import usage_recorder
    usage = usage_recorder.daily_summary(days)
    return {
        "kpis": {
            "total_customers": total,
            "l3_plus": l3_plus,
            "high_intent": stage_counts["high_intent"],
            "enrolled": stage_counts["enrolled"],
            "won": stage_counts["won"],
            "today_messages": today_messages,
        },
        "stage_distribution": [
            {"stage": s, "label": STAGE_LABELS[s], "count": stage_counts[s]}
            for s in STAGES
            if stage_counts[s] > 0
        ],
        "daily_new": [{"date": d, "count": daily[d]} for d in sorted(daily)],
        "usage": usage,
    }
