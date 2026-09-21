"""监控告警 API：规则管理、告警事件、测试通知"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.alerting import alert_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["alerting"], dependencies=[Depends(require_api_key)])


class RuleModel(BaseModel):
    rule_id: int | None = None
    rule_type: str = ""
    name: str = ""
    enabled: int = 1
    threshold: float = 0
    window_seconds: int = 300
    channels: str = "webhook"
    receivers: str = "叙白"
    cooldown_seconds: int = 600


class TestModel(BaseModel):
    title: str = "测试告警"
    content: str = "这是一条测试告警，确认通知通道正常。"


@router.get("/alerting/rules")
async def list_rules():
    return {"items": alert_manager.list_rules()}


@router.post("/alerting/rules", dependencies=[Depends(require_admin)])
async def save_rule(req: RuleModel):
    return {"ok": True, "rule": alert_manager.upsert_rule(**req.model_dump())}


@router.delete("/alerting/rules/{rule_id}", dependencies=[Depends(require_admin)])
async def delete_rule(rule_id: int):
    return {"ok": alert_manager.delete_rule(rule_id)}


@router.get("/alerting/events")
async def list_events(limit: int = 100):
    return {"items": alert_manager.list_events(limit)}


@router.post("/alerting/test", dependencies=[Depends(require_admin)])
async def test_alert(req: TestModel):
    return alert_manager.test_send(req.title, req.content)


@router.post("/alerting/check", dependencies=[Depends(require_admin)])
async def run_checks():
    alert_manager.run_checks()
    return {"ok": True}
