"""赢单引擎接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.security import require_admin, require_api_key
from core.winning import winning_manager

router = APIRouter(prefix="/api/v1", tags=["winning"], dependencies=[Depends(require_api_key)])


class GenericModel(BaseModel):
    fields: dict = {}


@router.get("/winning/differentiators")
async def list_differentiators(active_only: bool = Query(False), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"items": filter_by_tenant(winning_manager.list_differentiators(active_only=active_only), tenant_id)}


@router.post("/winning/differentiators", dependencies=[Depends(require_admin)])
async def create_differentiator(req: GenericModel):
    return {"item": winning_manager.create_differentiator(**req.fields)}


@router.patch("/winning/differentiators/{item_id}", dependencies=[Depends(require_admin)])
async def update_differentiator(item_id: int, req: GenericModel):
    return {"item": winning_manager.update_differentiator(item_id, **req.fields)}

@router.delete("/winning/differentiators/{item_id}", dependencies=[Depends(require_admin)])
async def delete_differentiator(item_id: int):
    return {"deleted": winning_manager.delete_differentiator(item_id)}


@router.get("/winning/evidence")
async def list_evidence(evidence_type: str = Query(""), keyword: str = Query(""), limit: int = Query(200, le=1000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"items": filter_by_tenant(winning_manager.list_evidence(evidence_type=evidence_type, keyword=keyword, limit=limit), tenant_id)}


@router.post("/winning/evidence", dependencies=[Depends(require_admin)])
async def create_evidence(req: GenericModel):
    return {"item": winning_manager.create_evidence(**req.fields)}


@router.patch("/winning/evidence/{item_id}", dependencies=[Depends(require_admin)])
async def update_evidence(item_id: int, req: GenericModel):
    return {"item": winning_manager.update_evidence(item_id, **req.fields)}

@router.delete("/winning/evidence/{item_id}", dependencies=[Depends(require_admin)])
async def delete_evidence(item_id: int):
    return {"deleted": winning_manager.delete_evidence(item_id)}


@router.get("/winning/tools")
async def list_tools(tool_type: str = Query(""), limit: int = Query(200, le=1000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"items": filter_by_tenant(winning_manager.list_tools(tool_type=tool_type, limit=limit), tenant_id)}


@router.post("/winning/tools", dependencies=[Depends(require_admin)])
async def create_tool(req: GenericModel):
    return {"item": winning_manager.create_tool(**req.fields)}


@router.patch("/winning/tools/{item_id}", dependencies=[Depends(require_admin)])
async def update_tool(item_id: int, req: GenericModel):
    return {"item": winning_manager.update_tool(item_id, **req.fields)}

@router.delete("/winning/tools/{item_id}", dependencies=[Depends(require_admin)])
async def delete_tool(item_id: int):
    return {"deleted": winning_manager.delete_tool(item_id)}
