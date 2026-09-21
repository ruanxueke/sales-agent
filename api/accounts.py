"""企业账号：登录、用户管理"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from core import login_guard
from core.enterprise import enterprise
from core.security import (
    client_ip,
    current_actor,
    current_tenant,
    require_admin,
    require_api_key,
)
from core.tenant import tenant_manager
from core.rbac import (
    create_service_key,
    list_service_keys,
    permissions_for,
    revoke_service_key,
)

router = APIRouter(prefix="/api/v1", tags=["accounts"])


class LoginModel(BaseModel):
    username: str
    password: str

class RegisterModel(BaseModel):
    company_name: str
    username: str
    password: str
    name: str = ""
    phone: str = ""


class UserCreate(BaseModel):
    username: str
    password: str
    name: str = ""
    role: str = "sales"


class UserStatus(BaseModel):
    status: str


class ServiceKeyCreate(BaseModel):
    name: str
    role: str = "api_service"
    scopes: list[str] = Field(default_factory=list)
    expires_at: str = ""


@router.post("/auth/register")
async def register(req: RegisterModel, request: Request):
    company = (req.company_name or "").strip()
    username = (req.username or "").strip()
    if not company or not username or not req.password:
        return {"ok": False, "error": "企业名称、用户名、密码不能为空"}
    # 未鉴权的自助注册按 IP 限流，避免被刷出成百上千个租户。
    _, allowed = login_guard.hit(
        "register:" + (client_ip(request) or "unknown"),
        limit=login_guard.REGISTER_MAX_PER_WINDOW,
        window=login_guard.REGISTER_WINDOW,
    )
    if not allowed:
        return {"ok": False, "error": "注册过于频繁，请稍后再试"}
    try:
        tenant = tenant_manager.create_tenant(company, plan="trial", seats=5)
        user = enterprise.create_user(username, req.password, req.name or "", role="owner")
        tenant_manager.add_member(tenant["id"], user["id"], role="owner")
        result = enterprise.login(username, req.password, ip=client_ip(request))
        return {
            "ok": True,
            "token": (result or {}).get("token", ""),
            "user": (result or {}).get("user"),
            "tenant": tenant,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"开通失败: {e}"}

@router.post("/auth/login")
async def login(req: LoginModel, request: Request):
    result = enterprise.login(req.username, req.password, ip=client_ip(request))
    if not result:
        return {"ok": False, "error": "用户名或密码错误"}
    return {"ok": True, **result}


@router.get("/accounts/me", dependencies=[Depends(require_api_key)])
async def me(request: Request):
    actor = current_actor(request)
    return {
        "ok": True,
        "mode": actor.get("kind"),
        "tenant_id": current_tenant(request),
        "role": actor.get("role") or "service",
        "scopes": actor.get("scopes") or [],
        "permissions": sorted(
            permissions_for(
                actor.get("role") or "service",
                actor.get("scopes") or [],
            )
        ),
    }


@router.get("/accounts/users", dependencies=[Depends(require_admin)])
async def list_users(request: Request):
    return {"items": enterprise.list_users(tenant_id=current_tenant(request))}


@router.post("/accounts/users", dependencies=[Depends(require_admin)])
async def create_user(req: UserCreate, request: Request):
    try:
        tenant_id = current_tenant(request)
        user = enterprise.create_user(
            req.username,
            req.password,
            req.name,
            req.role,
            tenant_id=tenant_id,
        )
        tenant_manager.add_member(tenant_id, user["id"], req.role)
        return {"ok": True, "user": {k: user[k] for k in ("id", "username", "name", "role", "status", "tenant_id")}}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.patch("/accounts/users/{user_id}/status", dependencies=[Depends(require_admin)])
async def user_status(user_id: int, req: UserStatus, request: Request):
    return {
        "ok": enterprise.set_user_status(
            user_id,
            req.status,
            tenant_id=current_tenant(request),
        )
    }


@router.get("/accounts/service-keys", dependencies=[Depends(require_admin)])
async def get_service_keys(request: Request):
    return {"items": list_service_keys(current_tenant(request))}


@router.post("/accounts/service-keys", dependencies=[Depends(require_admin)])
async def post_service_key(req: ServiceKeyCreate, request: Request):
    actor = current_actor(request)
    key = create_service_key(
        tenant_id=current_tenant(request),
        name=req.name,
        role=req.role,
        scopes=req.scopes,
        expires_at=req.expires_at,
        created_by=actor.get("role") or actor.get("kind") or "admin",
    )
    return {"ok": True, "key": key}


@router.post("/accounts/service-keys/{key_id}/revoke", dependencies=[Depends(require_admin)])
async def revoke_key(key_id: int, request: Request):
    return {
        "ok": revoke_service_key(
            key_id,
            tenant_id=current_tenant(request),
        )
    }
