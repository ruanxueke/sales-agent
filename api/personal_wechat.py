"""个人微信本地桥接 API：事件接收、回复任务认领和发送回执。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import BaseModel, Field

from core.personal_wechat import personal_wechat_service
from core.security import current_tenant, require_api_key

router = APIRouter(
    prefix="/api/v1/personal-wechat",
    tags=["personal-wechat"],
    dependencies=[Depends(require_api_key)],
)


class PersonalWechatEvent(BaseModel):
    # 兼容字段：租户以鉴权凭据为准（见 core/security.py 的「凭据即租户」），
    # 请求体里自报的 tenant_id 一律忽略，避免客户端伪造跨租户数据。
    tenant_id: int = 0
    account_id: str
    channel: str = "personal_wechat"
    target_type: str = "contact"
    target_name: str = ""
    target_username: str
    sender_name: str = ""
    message_id: str = ""
    content: str
    created_at: int = 0
    is_self: bool = False
    msg_type: str = "text"
    mode: str = "draft"


class TaskAck(BaseModel):
    status: str
    sent_at: str = ""
    error: str = ""
    failure_code: str = ""
    failure_stage: str = ""
    diagnostic_path: str = ""


class BridgeHeartbeat(BaseModel):
    instance_id: str
    account_id: str = ""
    status: str = "online"
    mode: str = "draft"
    auto_discover_contacts: bool = False
    notify_on_message: bool = True
    wechat_login_detected: bool = False
    poll_interval_seconds: int = 10
    last_message_at: str = ""
    last_reply_at: str = ""
    last_error: str = ""
    detail: dict = Field(default_factory=dict)


class BridgeSettings(BaseModel):
    instance_id: str
    recognition_enabled: bool | None = None
    detect_wechat_login: bool | None = None
    notify_on_message: bool | None = None


class ContactNameItem(BaseModel):
    target_username: str
    target_name: str


class ContactNameSync(BaseModel):
    account_id: str
    contacts: list[ContactNameItem] = Field(default_factory=list)


@router.post("/events")
async def receive_event(
    req: PersonalWechatEvent,
    background_tasks: BackgroundTasks,
    request: Request,
):
    payload = req.model_dump()
    result = personal_wechat_service.ingest_event(
        payload,
        tenant_id=current_tenant(request),
    )
    if result.get("ok") and result.get("status") == "generating" and result.get("task_id"):
        background_tasks.add_task(
            personal_wechat_service.generate_task,
            result["task_id"],
        )
    return result


@router.post("/contacts/sync")
async def sync_contact_names(req: ContactNameSync, request: Request):
    return personal_wechat_service.sync_contact_names(
        tenant_id=current_tenant(request),
        account_id=req.account_id,
        contacts=[item.model_dump() for item in req.contacts],
    )


@router.get("/tasks")
async def claim_tasks(
    account_id: str = Query(..., min_length=1),
    instance_id: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
    claim: bool = Query(True),
    request: Request = None,
):
    if not claim:
        items = personal_wechat_service.list_pending_tasks(
            tenant_id=current_tenant(request),
            account_id=account_id,
            limit=limit,
        )
        return {"items": items, "count": len(items)}
    items = personal_wechat_service.claim_tasks(
        tenant_id=current_tenant(request),
        account_id=account_id,
        limit=limit,
        claimed_by=instance_id,
    )
    return {"items": items, "count": len(items)}


@router.post("/tasks/{task_id}/ack")
async def acknowledge_task(
    task_id: str,
    req: TaskAck,
    request: Request,
):
    return personal_wechat_service.ack_task(
        task_id=task_id,
        status=req.status,
        tenant_id=current_tenant(request),
        error=req.error,
        sent_at=req.sent_at,
        failure_code=req.failure_code,
        failure_stage=req.failure_stage,
        diagnostic_path=req.diagnostic_path,
    )


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, request: Request):
    return personal_wechat_service.retry_task(
        task_id=task_id,
        tenant_id=current_tenant(request),
    )


@router.post("/bridge/heartbeat")
async def bridge_heartbeat(req: BridgeHeartbeat, request: Request):
    return personal_wechat_service.heartbeat(
        req.model_dump(),
        tenant_id=current_tenant(request),
    )


@router.get("/status")
async def personal_wechat_status(
    instance_id: str = Query(""),
    request: Request = None,
):
    return personal_wechat_service.status(
        tenant_id=current_tenant(request),
        instance_id=instance_id,
    )


@router.get("/metrics")
async def personal_wechat_metrics(
    account_id: str = Query(""),
    request: Request = None,
):
    return personal_wechat_service.metrics(
        tenant_id=current_tenant(request),
        account_id=account_id,
    )


@router.get("/settings")
async def get_bridge_settings(
    instance_id: str = Query(..., min_length=1),
    request: Request = None,
):
    return personal_wechat_service.get_settings(
        instance_id=instance_id,
        tenant_id=current_tenant(request),
    )


@router.post("/settings")
async def update_bridge_settings(req: BridgeSettings, request: Request):
    return personal_wechat_service.update_settings(
        req.model_dump(exclude_none=True),
        tenant_id=current_tenant(request),
    )
