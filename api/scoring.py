"""行为事件与动态意向评分接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.scoring import score_engine
from core.security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["scoring"], dependencies=[Depends(require_api_key)])


class BehaviorModel(BaseModel):
    session_id: str
    event_type: str
    event_value: str = ""
    source: str = ""


@router.post("/behavior")
async def record_behavior(req: BehaviorModel):
    return score_engine.record_event(
        session_id=req.session_id,
        event_type=req.event_type,
        event_value=req.event_value,
        source=req.source,
    )


@router.get("/behavior/stats")
async def behavior_stats():
    return score_engine.stats()


@router.get("/behavior/{session_id}")
async def list_behavior(session_id: str):
    return {"events": score_engine.list_events(session_id)}
