"""视觉受管执行器 API：状态、心跳、暂停/恢复、发送计量、任务中心、审计、去重、人工接管。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.security import require_admin, require_api_key
from core.vision import vision_agent

router = APIRouter(prefix="/api/v1", tags=["vision-agent"], dependencies=[Depends(require_api_key)])


class HeartbeatModel(BaseModel):
    instance_id: str = ""
    mode: str = ""
    detail: str = ""
    contact: str = ""


class PauseModel(BaseModel):
    paused: bool = True
    instance_id: str = ""


class SendModel(BaseModel):
    count: int = 1
    instance_id: str = ""


class AuditModel(BaseModel):
    action: str
    detail: dict = Field(default_factory=dict)
    instance_id: str = ""


class ReplyModel(BaseModel):
    content: str
    session_id: str = ""
    contact: str = ""
    mode: str = ""
    source: str = ""
    instance_id: str = ""


class SeenModel(BaseModel):
    instance_id: str = ""
    fingerprint: str


class TaskCreateModel(BaseModel):
    mode: str = "wecom"
    contact: str
    content: str
    instance_id: str = ""
    scheduled_at: str = ""
    priority: int = 0


class ClaimModel(BaseModel):
    instance_id: str = ""
    limit: int = 1
    mode: str = ""


class TaskCompleteModel(BaseModel):
    task_id: str
    status: str
    note: str = ""
    instance_id: str = ""


class HumanModeModel(BaseModel):
    instance_id: str = ""
    contact: str
    active: bool = True


@router.get("/vision/status")
async def vision_status():
    return vision_agent.status()


@router.post("/vision/heartbeat")
async def vision_heartbeat(req: HeartbeatModel):
    return vision_agent.heartbeat(req.instance_id, req.mode, req.detail, req.contact)


@router.post("/vision/pause", dependencies=[Depends(require_admin)])
async def vision_pause(req: PauseModel):
    return vision_agent.set_paused(req.paused, req.instance_id)


@router.post("/vision/record-send")
async def vision_record_send(req: SendModel):
    return vision_agent.record_send(req.count, req.instance_id)


@router.post("/vision/audit")
async def vision_audit(req: AuditModel):
    return vision_agent.audit(req.action, req.detail, req.instance_id)


@router.get("/vision/audit")
async def vision_audit_list(limit: int = 100, instance_id: str = "", action: str = ""):
    return {"ok": True, "records": vision_agent.list_audit(limit=limit, instance_id=instance_id, action=action)}


@router.post("/vision/mark-seen")
async def vision_mark_seen(req: SeenModel):
    return vision_agent.mark_seen(req.instance_id, req.fingerprint)


@router.post("/vision/reply")
async def vision_reply(req: ReplyModel):
    return vision_agent.reply(
        req.content,
        session_id=req.session_id,
        contact=req.contact,
        mode=req.mode,
        source=req.source,
        instance_id=req.instance_id,
    )


@router.get("/vision/tasks")
async def vision_tasks(instance_id: str = "", mode: str = "", status: str = "", limit: int = 100):
    return {"ok": True, "tasks": vision_agent.list_tasks(instance_id=instance_id, mode=mode, status=status, limit=limit)}


@router.post("/vision/tasks", dependencies=[Depends(require_admin)])
async def vision_task_create(req: TaskCreateModel):
    return vision_agent.create_task(
        req.mode,
        req.contact,
        req.content,
        instance_id=req.instance_id,
        scheduled_at=req.scheduled_at,
        priority=req.priority,
    )


@router.post("/vision/tasks/claim")
async def vision_task_claim(req: ClaimModel):
    return {"ok": True, "tasks": vision_agent.claim_tasks(req.instance_id, req.limit, req.mode)}


@router.post("/vision/tasks/complete")
async def vision_task_complete(req: TaskCompleteModel):
    return vision_agent.complete_task(req.task_id, req.status, req.note, req.instance_id)


@router.post("/vision/tasks/cancel", dependencies=[Depends(require_admin)])
async def vision_task_cancel(req: TaskCompleteModel):
    return vision_agent.cancel_task(req.task_id)


@router.post("/vision/handover/resolve", dependencies=[Depends(require_admin)])
async def vision_human_resolve(req: HumanModeModel):
    return vision_agent.mark_human_mode(req.instance_id, req.contact, req.active)
