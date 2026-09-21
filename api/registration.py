"""自助注册与试用：注册企业 → 创建租户 → 创建管理员 → 开通试用订阅"""
from __future__ import annotations
from fastapi import APIRouter, Request
from pydantic import BaseModel

from core import login_guard
from core.billing import billing
from core.enterprise import enterprise
from core.security import client_ip
from core.tenant import tenant_manager

router = APIRouter(prefix="/api/v1", tags=["registration"])


class RegisterModel(BaseModel):
    company: str
    username: str
    password: str
    name: str = ""
    phone: str = ""


@router.post("/registration/register")
async def register(req: RegisterModel, request: Request):
    # 未鉴权的自助注册按 IP 限流，避免被刷出成百上千个租户。
    _, allowed = login_guard.hit(
        "register:" + (client_ip(request) or "unknown"),
        limit=login_guard.REGISTER_MAX_PER_WINDOW,
        window=login_guard.REGISTER_WINDOW,
    )
    if not allowed:
        return {"ok": False, "error": "注册过于频繁，请稍后再试"}
    try:
        tenant = tenant_manager.create_tenant(req.company, "trial", seats=5)
        user = enterprise.create_user(req.username, req.password, req.name, "owner")
        tenant_manager.add_member(tenant["id"], user["id"], "owner")
        subscription = billing.subscribe(tenant["id"], "trial", days=14)
        return {
            "ok": True,
            "tenant": {"id": tenant["id"], "tenant_key": tenant["tenant_key"], "name": tenant["name"], "plan": tenant["plan"]},
            "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
            "subscription": subscription,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"注册失败: {e}"}
