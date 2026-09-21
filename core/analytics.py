"""数据智能：转化漏斗、渠道 ROI、效果对比（基于现有 CRM 数据实时计算）"""
from __future__ import annotations
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import settings

DB_PATH = Path(settings.DATA_DIR) / "customers.db"

STAGES = ["new", "understanding", "recommended", "quoted", "high_intent", "enrolled", "won"]


def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


class AnalyticsManager:
    def funnel(self, days: int = 30) -> dict:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        c = _conn()
        rows = c.execute(
            "SELECT stage, COUNT(*) AS n FROM customers WHERE created_at>=? GROUP BY stage",
            (cutoff,),
        ).fetchall()
        counts = {r["stage"]: r["n"] for r in rows}
        c.close()
        total = sum(counts.values()) or 1
        steps = []
        for i, stage in enumerate(STAGES):
            n = counts.get(stage, 0)
            steps.append({
                "stage": stage,
                "count": n,
                "rate_from_top": round(n / total * 100, 1),
                "rate_from_prev": round(n / max(1, counts.get(STAGES[i - 1], 0)) * 100, 1) if i else 100.0,
            })
        return {"days": days, "steps": steps, "total": sum(counts.values())}

    def channel_roi(self, days: int = 30) -> list[dict]:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        c = _conn()
        rows = c.execute(
            """
            SELECT source, COUNT(*) AS leads,
                   SUM(CASE WHEN stage IN ('enrolled','won') THEN 1 ELSE 0 END) AS won,
                   COALESCE(SUM(o.amount), 0) AS revenue
            FROM customers cu LEFT JOIN orders o ON o.customer_id=cu.id
            WHERE cu.created_at>=? GROUP BY cu.source
            """,
            (cutoff,),
        ).fetchall()
        c.close()
        items = []
        for r in rows:
            source = r["source"] or "unknown"
            leads = r["leads"]
            won = r["won"] or 0
            revenue = r["revenue"] or 0
            cost = 0  # 广告成本由外部归因接口写入，未配置时为 0
            items.append({
                "channel": source,
                "leads": leads,
                "conversion": round(won / leads * 100, 1) if leads else 0,
                "revenue": round(revenue, 2),
                "cost": cost,
                "roi": round((revenue - cost) / cost, 2) if cost else None,
            })
        items.sort(key=lambda x: x["revenue"], reverse=True)
        return items

    def ai_impact(self, days: int = 30) -> dict:
        """AI 通道 vs 人工通道的基础效果对比（可扩展为更细粒度归因）"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        c = _conn()
        rows = c.execute(
            """
            SELECT source, COUNT(*) AS n,
                   SUM(CASE WHEN stage IN ('enrolled','won') THEN 1 ELSE 0 END) AS won
            FROM customers WHERE created_at>=? GROUP BY source
            """,
            (cutoff,),
        ).fetchall()
        c.close()
        out = {}
        for r in rows:
            out[r["source"]] = {
                "customers": r["n"],
                "won": r["won"] or 0,
                "win_rate": round((r["won"] or 0) / r["n"] * 100, 1) if r["n"] else 0,
            }
        return {"days": days, "channels": out}


analytics = AnalyticsManager()
