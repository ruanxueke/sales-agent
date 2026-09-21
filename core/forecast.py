"""预测分析：赢单概率、流失预警（启发式评分，可替换为模型接口）"""
from __future__ import annotations
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
from datetime import datetime
from pathlib import Path

from config.settings import settings

DB_PATH = Path(settings.DATA_DIR) / "customers.db"


def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _parse(ts: str):
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


class ForecastManager:
    def win_probability(self, customer: dict) -> float:
        """基于阶段、意向分、预算、交互热度的启发式赢单概率 0-1"""
        score = 0.0
        stage = (customer.get("stage") or "new")
        weights = {
            "new": 0.05, "understanding": 0.15, "recommended": 0.3,
            "quoted": 0.45, "high_intent": 0.65, "enrolled": 0.85, "won": 1.0,
        }
        score += weights.get(stage, 0.05) * 0.5
        intent = customer.get("intent_score") or 0
        score += min(1.0, intent / 100) * 0.3
        budget = (customer.get("budget") or "")
        if budget and budget not in ("", "未知"):
            score += 0.1
        next_follow = _parse(customer.get("next_follow_up") or "")
        if next_follow:
            score += 0.05
        return round(min(0.99, max(0.01, score)), 3)

    def churn_risk(self, customer: dict) -> float:
        """流失风险：阶段低 + 长期未跟进 + 无近期交互 => 高风险"""
        risk = 0.2
        stage = customer.get("stage") or "new"
        if stage in ("new", "understanding"):
            risk += 0.25
        if stage in ("rejected", "lost"):
            risk += 0.45
        next_follow = _parse(customer.get("next_follow_up") or "")
        if not next_follow:
            risk += 0.2
        updated = _parse(customer.get("updated_at") or "")
        if updated:
            days = (datetime.now() - updated).days
            if days > 7:
                risk += min(0.3, days / 30 * 0.3)
        return round(min(0.95, risk), 3)

    def list_forecasts(self, limit: int = 100) -> list[dict]:
        c = _conn()
        rows = c.execute(
            "SELECT * FROM customers WHERE stage NOT IN ('won','lost') ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        c.close()
        out = []
        for r in rows:
            d = dict(r)
            out.append({
                "customer_id": d.get("id"),
                "nickname": d.get("nickname") or "",
                "session_id": d.get("session_id") or "",
                "stage": d.get("stage"),
                "win_probability": self.win_probability(d),
                "churn_risk": self.churn_risk(d),
                "next_follow_up": d.get("next_follow_up") or "",
                "updated_at": d.get("updated_at") or "",
            })
        out.sort(key=lambda x: (x["win_probability"] + (1 - x["churn_risk"])), reverse=True)
        return out


forecast = ForecastManager()
