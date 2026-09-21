"""租户与权限 API：租户管理、成员、角色、配额、设置"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.security import require_admin, require_api_key
from core.tenant import tenant_manager

router = APIRouter(prefix="/api/v1", tags=["tenant"], dependencies=[Depends(require_api_key)])


class TenantCreate(BaseModel):
    name: str
    plan: str = "trial"
    seats: int = 5


class TenantUpdate(BaseModel):
    name: str = ""
    plan: str = ""
    status: str = ""
    seats: int = 0
    quota_customers: int = 0
    quota_messages: int = 0


class MemberAdd(BaseModel):
    user_id: int
    role: str = "sales"


class SettingItem(BaseModel):
    key: str
    value: str


@router.get("/tenants")
async def list_tenants():
    return {"items": tenant_manager.list_tenants()}


@router.post("/tenants", dependencies=[Depends(require_admin)])
async def create_tenant(req: TenantCreate):
    try:
        tenant = tenant_manager.create_tenant(req.name, req.plan, req.seats)
        return {"ok": True, "tenant": tenant}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: int):
    return {"tenant": tenant_manager.get_tenant(tenant_id), "settings": tenant_manager.get_settings(tenant_id)}


@router.patch("/tenants/{tenant_id}", dependencies=[Depends(require_admin)])
async def update_tenant(tenant_id: int, req: TenantUpdate):
    fields = {k: v for k, v in req.dict().items() if v}
    return {"ok": True, "tenant": tenant_manager.update_tenant(tenant_id, **fields)}


@router.get("/tenants/{tenant_id}/members")
async def list_members(tenant_id: int):
    return {"items": tenant_manager.list_members(tenant_id)}


@router.post("/tenants/{tenant_id}/members", dependencies=[Depends(require_admin)])
async def add_member(tenant_id: int, req: MemberAdd):
    try:
        return {"ok": tenant_manager.add_member(tenant_id, req.user_id, req.role)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.delete("/tenants/{tenant_id}/members/{user_id}", dependencies=[Depends(require_admin)])
async def remove_member(tenant_id: int, user_id: int):
    return {"ok": tenant_manager.remove_member(tenant_id, user_id)}


@router.post("/tenants/{tenant_id}/settings", dependencies=[Depends(require_admin)])
async def set_setting(tenant_id: int, req: SettingItem):
    tenant_manager.set_setting(tenant_id, req.key, req.value)
    return {"ok": True}


@router.get("/tenants/{tenant_id}/quota")
async def quota(tenant_id: int):
    customers = tenant_manager.check_quota(tenant_id, "customers")
    messages = tenant_manager.check_quota(tenant_id, "messages")
    return {
        "customers": {"ok": customers[0], "used": customers[1], "quota": customers[2]},
        "messages": {"ok": messages[0], "used": messages[1], "quota": messages[2]},
    }
