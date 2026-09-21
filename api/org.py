"""组织管理：成员创建绑定租户、角色调整、租户统计（复用 enterprise + tenant）"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.enterprise import enterprise
from core.security import require_admin, require_api_key
from core.tenant import tenant_manager

router = APIRouter(prefix="/api/v1", tags=["org"], dependencies=[Depends(require_api_key)])


class MemberCreate(BaseModel):
    tenant_id: int
    username: str
    password: str
    name: str = ""
    role: str = "sales"


class MemberRole(BaseModel):
    role: str


@router.post("/org/members", dependencies=[Depends(require_admin)])
async def create_member(req: MemberCreate):
    """创建账号并直接加入指定租户"""
    try:
        user = enterprise.create_user(req.username, req.password, req.name, req.role)
        tenant_manager.add_member(req.tenant_id, user["id"], req.role)
        return {
            "ok": True,
            "user": {k: user[k] for k in ("id", "username", "name", "role", "status")},
            "tenant_id": req.tenant_id,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"创建成员失败: {e}"}


@router.patch("/org/members/{user_id}/role", dependencies=[Depends(require_admin)])
async def update_member_role(user_id: int, req: MemberRole):
    try:
        return {"ok": tenant_manager.update_member_role(user_id, req.role)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.get("/org/overview")
async def org_overview():
    """组织管理总览：租户、成员、配额、套餐订阅"""
    from core.billing import billing
    tenants = tenant_manager.list_tenants()
    items = []
    for t in tenants:
        members = tenant_manager.list_members(t["id"])
        sub = billing.get_subscription(t["id"])
        quota_c = tenant_manager.check_quota(t["id"], "customers")
        quota_m = tenant_manager.check_quota(t["id"], "messages")
        items.append({
            "tenant": t,
            "members": members,
            "subscription": sub,
            "quota": {
                "customers": {"used": quota_c[1], "quota": quota_c[2]},
                "messages": {"used": quota_m[1], "quota": quota_m[2]},
            },
        })
    return {"items": items}


@router.get("/accounts/tenant-me")
async def tenant_me(request):
    from core.security import current_actor
    actor = current_actor(request)
    user = actor.get("user") or {}
    if not user:
        return {"ok": True, "tenant_id": 0, "role": actor.get("kind") or "api_key"}
    return {"ok": True, "user_id": user.get("id"), "tenant_id": user.get("tenant_id") or 0, "role": user.get("role") or "sales"}
