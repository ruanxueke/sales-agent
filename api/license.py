"""许可证与用量：套餐、席位、配额、过期时间。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core.security import current_actor, current_tenant, require_api_key
from core.tenant import tenant_manager

router = APIRouter(prefix="/api/v1", tags=["license"], dependencies=[Depends(require_api_key)])


@router.get("/license/status")
async def license_status(request: Request):
    tenant_id = current_tenant(request)
    if tenant_id:
        tenant = tenant_manager.get_tenant(tenant_id)
        if tenant:
            ok_c, used_c, quota_c = tenant_manager.check_quota(tenant_id, "customers")
            ok_m, used_m, quota_m = tenant_manager.check_quota(tenant_id, "messages")
            return {
                "ok": True,
                "mode": "tenant",
                "tenant_id": tenant_id,
                "tenant_name": tenant.get("name") or "",
                "plan": tenant.get("plan") or "trial",
                "status": tenant.get("status") or "active",
                "seats": tenant.get("seats") or 0,
                "expires_at": tenant.get("expires_at") or "",
                "customers": {"ok": ok_c, "used": used_c, "quota": quota_c},
                "messages": {"ok": ok_m, "used": used_m, "quota": quota_m},
            }
    actor = current_actor(request)
    role = (actor.get("user") or {}).get("role") or "super_admin"
    return {
        "ok": True,
        "mode": "super_admin",
        "tenant_id": 0,
        "tenant_name": "超级管理员",
        "role": role,
        "plan": "enterprise",
        "status": "active",
        "seats": 999,
        "expires_at": "",
        "customers": {"ok": True, "used": 0, "quota": 0},
        "messages": {"ok": True, "used": 0, "quota": 0},
    }
