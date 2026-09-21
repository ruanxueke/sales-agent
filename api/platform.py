"""平台化接口：自定义字段、角色、团队、BI"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.platform import platform_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["platform"], dependencies=[Depends(require_api_key)])


class FieldCreate(BaseModel):
    entity: str = "customer"
    field_name: str
    field_key: str
    field_type: str = "text"
    options: str = ""
    required: bool = False
    sort: int = 0


class FieldUpdate(BaseModel):
    field_name: str = ""
    field_type: str = ""
    options: str = ""
    required: bool = None
    enabled: bool = None
    sort: int = None


class ValuesModel(BaseModel):
    values: dict = {}


class RoleCreate(BaseModel):
    name: str
    permissions: list[str] = []
    description: str = ""


class MemberCreate(BaseModel):
    name: str
    nickname: str = ""
    role: str = "sales"
    phone: str = ""
    email: str = ""
    tenant_id: str = "default"


class MemberUpdate(BaseModel):
    name: str = ""
    nickname: str = ""
    role: str = ""
    phone: str = ""
    email: str = ""
    status: str = ""
    tenant_id: str = ""


@router.get("/custom-fields")
async def list_fields(entity: str = Query("")):
    return {"fields": platform_manager.list_fields(entity=entity)}


@router.post("/custom-fields", dependencies=[Depends(require_admin)])
async def create_field(req: FieldCreate):
    return {"field": platform_manager.create_field(**req.model_dump())}


@router.patch("/custom-fields/{field_id}", dependencies=[Depends(require_admin)])
async def update_field(field_id: int, req: FieldUpdate):
    data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    return {"field": platform_manager.update_field(field_id, **data)}


@router.get("/custom-fields/values/{entity}/{entity_id}")
async def get_values(entity: str, entity_id: int):
    return {"values": platform_manager.get_values(entity, entity_id)}


@router.post("/custom-fields/values/{entity}/{entity_id}", dependencies=[Depends(require_admin)])
async def set_values(entity: str, entity_id: int, req: ValuesModel):
    return {"values": platform_manager.set_values(entity, entity_id, req.values)}


@router.get("/roles", dependencies=[Depends(require_admin)])
async def list_roles():
    return {"roles": platform_manager.list_roles()}


@router.post("/roles", dependencies=[Depends(require_admin)])
async def create_role(req: RoleCreate):
    return {"role": platform_manager.create_role(req.name, req.permissions, req.description)}


@router.get("/team", dependencies=[Depends(require_admin)])
async def list_members(tenant_id: str = Query(""), status: str = Query("")):
    return {"members": platform_manager.list_members(tenant_id=tenant_id, status=status)}


@router.post("/team", dependencies=[Depends(require_admin)])
async def create_member(req: MemberCreate):
    return {"member": platform_manager.create_member(**req.model_dump())}


@router.patch("/team/{member_id}", dependencies=[Depends(require_admin)])
async def update_member(member_id: int, req: MemberUpdate):
    data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    return {"member": platform_manager.update_member(member_id, **data)}


@router.get("/bi/metrics")
async def bi_metrics(days: int = Query(7, ge=1, le=90)):
    return platform_manager.bi_metrics(days=days)
