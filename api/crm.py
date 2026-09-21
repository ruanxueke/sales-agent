"""客户档案查询接口：查看客户信息和销售阶段变化"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from core.security import (
    current_tenant,
    permission_required,
    require_admin,
)
from core.sales_crm import crm
import logging
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1", tags=["crm"])


class ProfileUpdate(BaseModel):
    name: str = ""
    nickname: str = ""
    phone: str = ""
    wechat_id: str = ""
    identity: str = ""
    level: str = ""
    goal: str = ""
    budget: str = ""
    interest: str = ""
    stage: str = ""
    intent_level: str = ""
    intent_score: int = None
    notes: str = ""
    next_follow_up: str = ""


@router.get("/customers", dependencies=[Depends(permission_required("customer:read"))])
async def list_customers(request: Request):
    return {"customers": crm.list_customers(tenant_id=current_tenant(request))}


@router.get(
    "/customer/{session_id}",
    dependencies=[Depends(permission_required("customer:read"))],
)
async def get_customer(session_id: str, request: Request):
    tenant_id = current_tenant(request)
    customer = crm.get_by_session(session_id, tenant_id=tenant_id)
    if not customer:
        return {"customer": None}
    customer["stage_log"] = crm.stage_log(customer["id"], tenant_id=tenant_id)
    customer["chat_log"] = crm.get_chat_log(
        customer["id"],
        limit=30,
        tenant_id=tenant_id,
    )
    return {"customer": customer}


@router.patch(
    "/customer/{session_id}",
    dependencies=[Depends(permission_required("customer:write"))],
)
async def update_customer(session_id: str, req: ProfileUpdate, request: Request):
    tenant_id = current_tenant(request)
    customer = crm.get_by_session(session_id, tenant_id=tenant_id)
    if not customer:
        return {"customer": None}
    data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    if data.get("stage"):
        try:
            crm.advance_stage(
                customer["id"],
                data.pop("stage"),
                trigger="中台手动修改",
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning("客户阶段流转失败，阶段与日志可能不一致: %s", e)
    crm.update_profile(customer["id"], tenant_id=tenant_id, **data)
    updated = crm.get(customer["id"], tenant_id=tenant_id)
    return {"customer": updated}


@router.post("/customers/backfill-display-id", dependencies=[Depends(require_admin)])
async def backfill_display_ids(request: Request):
    """按微信昵称补全唯一显示编号；乱码昵称自动修复为 客户+编号，重复追加 2、3..."""
    tenant_id = current_tenant(request)
    customers = crm.list_customers(tenant_id=tenant_id)
    used = {c.get("display_id") for c in customers if c.get("display_id") and "?" not in c.get("display_id")}
    updated = 0

    def clean(value):
        return str(value or "").replace("?", "").replace("\ufffd", "").strip()

    for c in customers:
        nick = clean(c.get("nickname")) or f"客户{c['id']}"
        if c.get("nickname") != nick:
            crm.update_profile(c["id"], tenant_id=tenant_id, nickname=nick)
            updated += 1
        current = clean(c.get("display_id"))
        if c.get("display_id") != current or not current or c.get("display_id") == c.get("session_id"):
            base = nick
            candidate = base
            index = 2
            while candidate in used:
                candidate = f"{base}{index}"
                index += 1
            crm.update_profile(c["id"], tenant_id=tenant_id, display_id=candidate)
            used.add(candidate)
            updated += 1
    return {"updated": updated}


@router.post("/customer/{session_id}/erase", dependencies=[Depends(require_admin)])
async def erase_customer(session_id: str, request: Request):
    from core.compliance_flow import compliance_flow

    return compliance_flow.erase_customer(
        session_id,
        tenant_id=current_tenant(request),
        actor="admin",
    )


@router.get(
    "/notifications",
    dependencies=[Depends(permission_required("customer:read"))],
)
async def list_notifications(request: Request):
    return {
        "notifications": crm.list_notifications(
            tenant_id=current_tenant(request)
        )
    }
