"""企业级数据智能：实时经营总览、转化漏斗、ROI 归因、趋势、团队战报、自定义报表与导出。

数据源统一走 SQLAlchemy（PostgreSQL / SQLite 均兼容），
查询结果实时计算，支持按当前租户过滤；管理员（API Key）看全部。
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta

from sqlalchemy import text

from core.db import session_scope
from core.models import BIReport

STAGE_LABELS = {
    "new": "陌生",
    "understanding": "兴趣了解",
    "recommended": "意向明确",
    "high_intent": "高意向",
    "enrolled": "已报名",
    "won": "已成交",
    "after_sales": "售后",
    "lost": "流失",
}
STAGE_ORDER = ["new", "understanding", "recommended", "high_intent", "enrolled", "won"]
ORDER_PAID_STATUS = "('paid', 'completed', 'won', 'delivered')"
CHANNEL_LABELS = {
    "wechat": "个人微信",
    "official": "公众号",
    "webchat": "网页客服",
    "import": "导入",
    "ad": "广告",
    "referral": "转介绍",
    "unknown": "未知",
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cut(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _cut_date(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _tf(tenant_id, column: str = "tenant_id") -> str:
    return f"{column}=:tid" if tenant_id is not None else "1=1"


def _params(tenant_id, **extra) -> dict:
    params = {"tid": tenant_id or 0}
    params.update(extra)
    return params


def _rows(session, sql: str, params: dict):
    try:
        return [dict(r) for r in session.execute(text(sql), params).mappings()]
    except Exception:
        return []


def _one(session, sql: str, params: dict) -> dict:
    try:
        row = session.execute(text(sql), params).mappings().first()
        return dict(row) if row else {}
    except Exception:
        return {}


def _num(value, default=0):
    try:
        return float(value or default)
    except Exception:
        return default


def _int(value, default=0):
    try:
        return int(value or default)
    except Exception:
        return default


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _zh_channel(value: str) -> str:
    return CHANNEL_LABELS.get(value or "", value or "未知")


# ============================================================
# 实时经营总览
# ============================================================

def overview(tenant_id: int | None = None, days: int = 7) -> dict:
    cut = _cut(days)
    p = _params(tenant_id, cut=cut, now=_now_str())
    with session_scope(read_only=True) as s:
        customers_total = _int(_one(s, "SELECT COUNT(*) AS n FROM customers", {}).get("n"))
        customers_new = _int(_one(s, "SELECT COUNT(*) AS n FROM customers WHERE created_at>=:cut", {"cut": cut}).get("n"))
        won = _int(_one(s, "SELECT COUNT(*) AS n FROM customers WHERE stage IN ('won','enrolled')", {}).get("n"))
        leads_total = _int(_one(s, f"SELECT COUNT(*) AS n FROM leads WHERE {_tf(tenant_id)}", p).get("n"))
        leads_new = _int(_one(s, f"SELECT COUNT(*) AS n FROM leads WHERE {_tf(tenant_id)} AND created_at>=:cut", p).get("n"))
        order_row = _one(
            s,
            f"SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS rev FROM orders "
            f"WHERE {_tf(tenant_id)} AND status IN {ORDER_PAID_STATUS} AND created_at>=:cut",
            p,
        )
        messages = _int(_one(s, "SELECT COUNT(*) AS n FROM customer_chat_log WHERE created_at>=:cut", {"cut": cut}).get("n"))
        active_sessions = _int(_one(
            s, "SELECT COUNT(DISTINCT session_id) AS n FROM customer_chat_log WHERE created_at>=:cut", {"cut": cut}
        ).get("n"))
        avg_score = _num(_one(s, "SELECT COALESCE(AVG(total_score),0) AS v FROM conversation_scores WHERE created_at>=:cut", {"cut": cut}).get("v"))
        overdue = _int(_one(s, "SELECT COUNT(*) AS n FROM followup_tasks WHERE status='pending' AND due_at<:now", {"now": _now_str()}).get("n"))
        active_alerts = _int(_one(s, "SELECT COUNT(*) AS n FROM alert_rules WHERE enabled=1", {}).get("n"))

    conversion = round(won / customers_total * 100, 1) if customers_total else 0.0
    lead_conversion = round(leads_total and won / leads_total * 100 or 0, 1)
    return {
        "generated_at": _now_str(),
        "days": days,
        "kpis": {
            "customers_total": customers_total,
            "customers_new": customers_new,
            "won": won,
            "leads_total": leads_total,
            "leads_new": leads_new,
            "orders": _int(order_row.get("n")),
            "revenue": round(_num(order_row.get("rev")), 2),
            "messages": messages,
            "active_sessions": active_sessions,
            "avg_score": round(avg_score, 1),
            "overdue_followups": overdue,
            "active_alerts": active_alerts,
            "conversion_rate": conversion,
            "lead_conversion_rate": lead_conversion,
        },
    }


# ============================================================
# 转化漏斗
# ============================================================

def funnel(tenant_id: int | None = None, days: int = 30) -> dict:
    cut = _cut(days)
    p = _params(tenant_id, cut=cut)
    with session_scope(read_only=True) as s:
        rows = _rows(s, "SELECT stage, COUNT(*) AS n FROM customers WHERE created_at>=:cut GROUP BY stage", {"cut": cut})
        daily = _rows(s, "SELECT substr(created_at,1,10) AS d, COUNT(*) AS n FROM customers WHERE created_at>=:cut GROUP BY d ORDER BY d", {"cut": cut})
    counts = {r.get("stage") or "new": _int(r.get("n")) for r in rows}
    total = sum(counts.values())
    steps = []
    prev = total
    for stage in STAGE_ORDER:
        n = counts.get(stage, 0)
        steps.append({
            "stage": stage,
            "label": STAGE_LABELS.get(stage, stage),
            "count": n,
            "rate_from_top": round(n / total * 100, 1) if total else 0.0,
            "rate_from_prev": round(n / prev * 100, 1) if prev else 0.0,
        })
        prev = n
    return {
        "days": days,
        "total": total,
        "steps": steps,
        "daily": [{"date": r.get("d"), "count": _int(r.get("n"))} for r in daily],
    }


# ============================================================
# ROI 归因：渠道 / 广告 / 销售
# ============================================================

def roi(tenant_id: int | None = None, days: int = 30) -> dict:
    cut = _cut(days)
    cut_d = _cut_date(days)
    p = _params(tenant_id, cut=cut, cut_d=cut_d)
    with session_scope(read_only=True) as s:
        channel_rows = _rows(
            s,
            f"SELECT source, COUNT(*) AS n, "
            f"SUM(CASE WHEN stage IN ('won','enrolled') THEN 1 ELSE 0 END) AS won "
            f"FROM leads WHERE {_tf(tenant_id)} AND created_at>=:cut GROUP BY source",
            p,
        )
        channel_rev = _rows(
            s,
            f"SELECT l.source, COALESCE(SUM(o.amount),0) AS rev FROM orders o "
            f"LEFT JOIN leads l ON o.lead_id=l.id "
            f"WHERE {_tf(tenant_id, 'o.tenant_id')} AND o.status IN {ORDER_PAID_STATUS} AND o.created_at>=:cut "
            f"GROUP BY l.source",
            p,
        )
        ad_rows = _rows(
            s,
            "SELECT c.name AS campaign, c.channel, "
            "SUM(m.impressions) AS impressions, SUM(m.clicks) AS clicks, "
            "SUM(m.conversions) AS conversions, COALESCE(SUM(m.cost),0) AS cost, "
            "COALESCE(SUM(m.revenue),0) AS rev "
            "FROM ad_metrics m LEFT JOIN campaigns c ON c.id=m.campaign_id "
            "WHERE m.metric_date>=:cut_d GROUP BY c.name, c.channel",
            p,
        )
        sales_rows = _rows(
            s,
            f"SELECT l.owner, COUNT(*) AS n, "
            f"SUM(CASE WHEN l.stage IN ('won','enrolled') THEN 1 ELSE 0 END) AS won, "
            f"COALESCE(SUM(CASE WHEN o.status IN {ORDER_PAID_STATUS} THEN o.amount ELSE 0 END),0) AS rev "
            f"FROM leads l LEFT JOIN orders o ON o.lead_id=l.id "
            f"WHERE {_tf(tenant_id, 'l.tenant_id')} AND l.created_at>=:cut GROUP BY l.owner",
            p,
        )

    rev_by_source = {r.get("source") or "unknown": _num(r.get("rev")) for r in channel_rev}
    channels = []
    total_leads = 0
    total_revenue = 0.0
    for r in channel_rows:
        source = r.get("source") or "unknown"
        n = _int(r.get("n"))
        won = _int(r.get("won"))
        revenue = rev_by_source.get(source, 0.0)
        total_leads += n
        total_revenue += revenue
        channels.append({
            "channel": _zh_channel(source),
            "channel_key": source,
            "leads": n,
            "won": won,
            "conversion": round(won / n * 100, 1) if n else 0.0,
            "revenue": round(revenue, 2),
            "cost": 0,
            "roi": None,
        })
    channels.sort(key=lambda x: x["revenue"], reverse=True)

    ads = []
    total_ad_cost = 0.0
    total_ad_rev = 0.0
    for r in ad_rows:
        cost = _num(r.get("cost"))
        rev = _num(r.get("rev"))
        total_ad_cost += cost
        total_ad_rev += rev
        ads.append({
            "campaign": r.get("campaign") or "未命名活动",
            "channel": _zh_channel(r.get("channel")),
            "impressions": _int(r.get("impressions")),
            "clicks": _int(r.get("clicks")),
            "conversions": _int(r.get("conversions")),
            "ctr": round(_int(r.get("clicks")) / _int(r.get("impressions")) * 100, 2) if _int(r.get("impressions")) else 0.0,
            "cost": round(cost, 2),
            "revenue": round(rev, 2),
            "roi": round((rev - cost) / cost, 2) if cost else None,
        })
    ads.sort(key=lambda x: x["revenue"], reverse=True)

    sales = []
    for r in sales_rows:
        n = _int(r.get("n"))
        won = _int(r.get("won"))
        rev = _num(r.get("rev"))
        sales.append({
            "owner": r.get("owner") or "未分配",
            "leads": n,
            "won": won,
            "conversion": round(won / n * 100, 1) if n else 0.0,
            "revenue": round(rev, 2),
        })
    sales.sort(key=lambda x: x["revenue"], reverse=True)

    return {
        "days": days,
        "channels": channels,
        "ads": ads,
        "sales": sales,
        "summary": {
            "total_leads": total_leads,
            "total_revenue": round(total_revenue, 2),
            "total_ad_cost": round(total_ad_cost, 2),
            "total_ad_revenue": round(total_ad_rev, 2),
            "overall_roi": round((total_ad_rev - total_ad_cost) / total_ad_cost, 2) if total_ad_cost else None,
        },
    }


# ============================================================
# 趋势：客户 / 线索 / 订单 / 收入 / 消息
# ============================================================

def trends(tenant_id: int | None = None, days: int = 30) -> dict:
    cut = _cut(days)
    p = _params(tenant_id, cut=cut)
    with session_scope(read_only=True) as s:
        customer_rows = _rows(s, "SELECT substr(created_at,1,10) AS d, COUNT(*) AS n FROM customers WHERE created_at>=:cut GROUP BY d", {"cut": cut})
        lead_rows = _rows(s, f"SELECT substr(created_at,1,10) AS d, COUNT(*) AS n FROM leads WHERE {_tf(tenant_id)} AND created_at>=:cut GROUP BY d", p)
        order_rows = _rows(
            s,
            f"SELECT substr(created_at,1,10) AS d, COUNT(*) AS n, COALESCE(SUM(amount),0) AS rev "
            f"FROM orders WHERE {_tf(tenant_id)} AND status IN {ORDER_PAID_STATUS} AND created_at>=:cut GROUP BY d",
            p,
        )
        message_rows = _rows(s, "SELECT substr(created_at,1,10) AS d, COUNT(*) AS n FROM customer_chat_log WHERE created_at>=:cut GROUP BY d", {"cut": cut})

    start = (datetime.now() - timedelta(days=days - 1)).date()
    dates = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    by_date = {d: {"customers": 0, "leads": 0, "orders": 0, "revenue": 0.0, "messages": 0} for d in dates}
    for r in customer_rows:
        d = r.get("d")
        if d in by_date:
            by_date[d]["customers"] = _int(r.get("n"))
    for r in lead_rows:
        d = r.get("d")
        if d in by_date:
            by_date[d]["leads"] = _int(r.get("n"))
    for r in order_rows:
        d = r.get("d")
        if d in by_date:
            by_date[d]["orders"] = _int(r.get("n"))
            by_date[d]["revenue"] = round(_num(r.get("rev")), 2)
    for r in message_rows:
        d = r.get("d")
        if d in by_date:
            by_date[d]["messages"] = _int(r.get("n"))
    return {
        "days": days,
        "rows": [{"date": d, **by_date[d]} for d in dates],
    }


# ============================================================
# 团队战报
# ============================================================

def team(tenant_id: int | None = None, days: int = 30) -> dict:
    cut = _cut(days)
    p = _params(tenant_id, cut=cut)
    with session_scope(read_only=True) as s:
        rows = _rows(
            s,
            f"SELECT l.owner, COUNT(*) AS n, "
            f"SUM(CASE WHEN l.stage IN ('won','enrolled') THEN 1 ELSE 0 END) AS won, "
            f"COALESCE(SUM(CASE WHEN o.status IN {ORDER_PAID_STATUS} THEN o.amount ELSE 0 END),0) AS rev "
            f"FROM leads l LEFT JOIN orders o ON o.lead_id=l.id "
            f"WHERE {_tf(tenant_id, 'l.tenant_id')} AND l.created_at>=:cut GROUP BY l.owner",
            p,
        )
    items = []
    for r in rows:
        n = _int(r.get("n"))
        won = _int(r.get("won"))
        rev = _num(r.get("rev"))
        items.append({
            "owner": r.get("owner") or "未分配",
            "leads": n,
            "won": won,
            "conversion": round(won / n * 100, 1) if n else 0.0,
            "revenue": round(rev, 2),
            "avg_order": round(rev / max(1, won), 2),
        })
    items.sort(key=lambda x: x["revenue"], reverse=True)
    return {"days": days, "items": items}


# ============================================================
# 自定义报表
# ============================================================

REPORT_DEFS = {
    "customers": {"table": "customers", "value": "COUNT(*) AS value", "label": "客户数", "tenant": False, "dims": ["date", "source", "stage"], "where": "created_at>=:cut"},
    "customers_new": {"table": "customers", "value": "COUNT(*) AS value", "label": "新增客户", "tenant": False, "dims": ["date", "source", "stage"], "where": "created_at>=:cut"},
    "won_customers": {"table": "customers", "value": "COUNT(*) AS value", "label": "成交客户", "tenant": False, "dims": ["date", "source", "stage"], "where": "stage IN ('won','enrolled') AND created_at>=:cut"},
    "leads": {"table": "leads", "value": "COUNT(*) AS value", "label": "线索数", "tenant": True, "dims": ["date", "source", "owner", "stage"], "where": "created_at>=:cut"},
    "leads_new": {"table": "leads", "value": "COUNT(*) AS value", "label": "新增线索", "tenant": True, "dims": ["date", "source", "owner", "stage"], "where": "created_at>=:cut"},
    "orders": {"table": "orders", "value": "COUNT(*) AS value", "label": "订单数", "tenant": True, "dims": ["date", "product"], "where": f"status IN {ORDER_PAID_STATUS} AND created_at>=:cut"},
    "revenue": {"table": "orders", "value": "COALESCE(SUM(amount),0) AS value", "label": "收入", "tenant": True, "dims": ["date", "product"], "where": f"status IN {ORDER_PAID_STATUS} AND created_at>=:cut"},
    "messages": {"table": "customer_chat_log", "value": "COUNT(*) AS value", "label": "消息量", "tenant": False, "dims": ["date"], "where": "created_at>=:cut"},
    "ad_cost": {"table": "ad_metrics", "value": "COALESCE(SUM(cost),0) AS value", "label": "广告成本", "tenant": False, "dims": ["date", "campaign"], "where": "metric_date>=:cut_d"},
    "ad_revenue": {"table": "ad_metrics", "value": "COALESCE(SUM(revenue),0) AS value", "label": "广告收入", "tenant": False, "dims": ["date", "campaign"], "where": "metric_date>=:cut_d"},
    "quality_avg": {"table": "conversation_scores", "value": "COALESCE(AVG(total_score),0) AS value", "label": "平均对话评分", "tenant": False, "dims": ["date"], "where": "created_at>=:cut"},
}

DIM_EXPR = {
    "date": "substr(created_at,1,10)",
    "source": "source",
    "owner": "owner",
    "stage": "stage",
    "product": "product_name",
    "campaign": "campaign_id",
}

DIM_LABELS = {
    "date": "日期",
    "source": "渠道",
    "owner": "销售",
    "stage": "阶段",
    "product": "产品",
    "campaign": "广告活动",
}


def report_meta() -> dict:
    return {
        "metrics": [{"key": k, "label": v["label"], "dimensions": v["dims"]} for k, v in REPORT_DEFS.items()],
        "dimensions": [{"key": k, "label": v} for k, v in DIM_LABELS.items()],
    }


def list_reports(tenant_id: int | None = None) -> list[dict]:
    with session_scope(read_only=True) as s:
        sql = "SELECT * FROM bi_reports"
        params = {}
        if tenant_id is not None:
            sql += " WHERE tenant_id=:tid"
            params["tid"] = tenant_id
        sql += " ORDER BY id DESC"
        rows = _rows(s, sql, params)
    for r in rows:
        r["filters"] = json.loads(r.get("filters_json") or "{}")
    return rows


def create_report(tenant_id: int | None, name: str, metric: str, dimension: str, days: int = 30, filters: dict | None = None, created_by: str = "") -> dict:
    if metric not in REPORT_DEFS:
        raise ValueError(f"不支持的指标: {metric}")
    if dimension not in REPORT_DEFS[metric]["dims"]:
        raise ValueError(f"指标 {metric} 不支持维度 {dimension}")
    with session_scope() as s:
        obj = BIReport(
            tenant_id=tenant_id or 0,
            name=(name or "").strip() or metric,
            metric=metric,
            dimension=dimension,
            days=max(1, min(365, int(days or 30))),
            filters_json=json.dumps(filters or {}, ensure_ascii=False),
            created_by=created_by or "",
        )
        s.add(obj)
        s.flush()
        return _row_to_dict(obj)


def delete_report(report_id: int, tenant_id: int | None = None) -> bool:
    with session_scope() as s:
        row = s.execute(
            text("SELECT id FROM bi_reports WHERE id=:id" + (" AND tenant_id=:tid" if tenant_id is not None else "")),
            {"id": report_id, "tid": tenant_id or 0},
        ).mappings().first()
        if not row:
            return False
        s.execute(text("DELETE FROM bi_reports WHERE id=:id"), {"id": report_id})
        return True


def run_report(report: dict, tenant_id: int | None = None) -> dict:
    metric = report.get("metric") or "customers"
    dimension = report.get("dimension") or "date"
    days = int(report.get("days") or 30)
    definition = REPORT_DEFS.get(metric)
    if not definition:
        return {"ok": False, "error": f"不支持的指标: {metric}"}
    if dimension not in definition["dims"]:
        return {"ok": False, "error": f"指标 {metric} 不支持维度 {dimension}"}

    table = definition["table"]
    dim_expr = "metric_date" if (table == "ad_metrics" and dimension == "date") else DIM_EXPR[dimension]
    wheres = [definition["where"]]
    params = {"cut": _cut(days), "cut_d": _cut_date(days)}
    if definition["tenant"] and tenant_id is not None:
        wheres.append("tenant_id=:tid")
        params["tid"] = tenant_id
    filters = report.get("filters") or {}
    for key, value in (filters or {}).items():
        if key in ("source", "owner", "stage", "product", "campaign") and value:
            col = DIM_EXPR.get(key)
            if col and col != "substr(created_at,1,10)":
                wheres.append(f"{col}=:f_{key}")
                params[f"f_{key}"] = value
    sql = f"SELECT {dim_expr} AS dimension, {definition['value']} FROM {table} WHERE " + " AND ".join(wheres)
    sql += f" GROUP BY {dim_expr} ORDER BY value DESC"
    with session_scope(read_only=True) as s:
        rows = _rows(s, sql, params)
    return {
        "ok": True,
        "name": report.get("name") or definition["label"],
        "metric": metric,
        "metric_label": definition["label"],
        "dimension": dimension,
        "dimension_label": DIM_LABELS.get(dimension, dimension),
        "days": days,
        "columns": ["dimension_label", "value"],
        "rows": rows,
    }


def export_csv(report: dict, tenant_id: int | None = None) -> str:
    result = run_report(report, tenant_id)
    if not result.get("ok"):
        return ""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([result["dimension_label"], result["metric_label"]])
    for r in result["rows"]:
        writer.writerow([r.get("dimension") or "", r.get("value") or 0])
    return buf.getvalue()
