"""AI 主动经营接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.aiops import aiops_manager
from core.security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["aiops"], dependencies=[Depends(require_api_key)])


class AskRequest(BaseModel):
    question: str


@router.post("/aiops/daily-briefing")
async def daily_briefing():
    return aiops_manager.daily_briefing()


@router.post("/aiops/deal-coach/{opportunity_id}")
async def deal_coach(opportunity_id: int):
    return aiops_manager.deal_coach(opportunity_id)


@router.post("/aiops/contract-risk/{contract_id}")
async def contract_risk(contract_id: int):
    return aiops_manager.contract_risk(contract_id)


@router.post("/aiops/ask-data")
async def ask_data(req: AskRequest):
    return aiops_manager.ask_data(req.question)


@router.get("/aiops/reports")
async def list_reports(report_type: str = Query(""), limit: int = Query(200, le=1000)):
    return {"reports": aiops_manager.list_reports(report_type=report_type, limit=limit)}


@router.get("/aiops/health")
async def health_detail():
    """详细健康指标（需鉴权）。

    `/health` 现在只返回 {"status":"ok"}：它不鉴权，而数据库异常信息里可能带
    完整 DSN（含口令），不适合对外。运维要看连接池/迁移版本请用这个端点。
    """
    from core.db import check_db_health, schema_revision
    from core.realtime import hub

    db = check_db_health()
    return {
        "status": db.get("status", "unknown"),
        "database": db,
        "schema_revision": schema_revision(),
        "ws_connections": hub.connection_count(),
    }
