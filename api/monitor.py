"""运行监控查询接口"""
from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel

from core.monitor import monitor

router = APIRouter(prefix="/api/v1", tags=["monitor"])


class HeartbeatRequest(BaseModel):
    source: str = "wechat"


@router.get("/monitor/metrics")
async def metrics(window: int = 300):
    return monitor.summary(window)


@router.post("/monitor/heartbeat")
async def heartbeat(payload: HeartbeatRequest):
    monitor.heartbeat(payload.source)
    return {"ok": True}
