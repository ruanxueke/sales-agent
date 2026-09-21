"""分析与预测 API：转化漏斗、渠道 ROI、AI 效果、赢单概率、流失预警"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query

from core.analytics import analytics
from core.forecast import forecast
from core.security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["analytics"], dependencies=[Depends(require_api_key)])


@router.get("/analytics/funnel")
async def funnel(days: int = Query(30, ge=1, le=365)):
    return analytics.funnel(days)


@router.get("/analytics/channel-roi")
async def channel_roi(days: int = Query(30, ge=1, le=365)):
    return {"items": analytics.channel_roi(days)}


@router.get("/analytics/ai-impact")
async def ai_impact(days: int = Query(30, ge=1, le=365)):
    return analytics.ai_impact(days)


@router.get("/forecast/win-probability")
async def win_probability(customer_id: int):
    import sqlite3
    from core.sales_crm import crm
    customer = crm.get(customer_id)
    if not customer:
        return {"ok": False, "error": "客户不存在"}
    return {"ok": True, "customer_id": customer_id, "win_probability": forecast.win_probability(customer)}


@router.get("/forecast/list")
async def forecast_list(limit: int = Query(100, le=500)):
    return {"items": forecast.list_forecasts(limit)}
