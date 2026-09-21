"""话术弹药库与案例投喂接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.ammo import ammo_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["ammo"], dependencies=[Depends(require_api_key)])


class GenericModel(BaseModel):
    fields: dict = {}


class CaseImportModel(BaseModel):
    content: str
    title: str = ""
    channel: str = ""


@router.get("/ammo/products")
async def list_products(active_only: bool = Query(False), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"products": filter_by_tenant(ammo_manager.list_products(active_only=active_only), tenant_id)}


@router.post("/ammo/products", dependencies=[Depends(require_admin)])
async def create_product(req: GenericModel):
    return {"product": ammo_manager.create_product(**req.fields)}


@router.patch("/ammo/products/{item_id}", dependencies=[Depends(require_admin)])
async def update_product(item_id: int, req: GenericModel):
    return {"product": ammo_manager.update_product(item_id, **req.fields)}

@router.delete("/ammo/products/{item_id}", dependencies=[Depends(require_admin)])
async def delete_product(item_id: int):
    return {"deleted": ammo_manager.delete_product(item_id)}


@router.get("/ammo/objections")
async def list_objections(active_only: bool = Query(False), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"objections": filter_by_tenant(ammo_manager.list_objections(active_only=active_only), tenant_id)}


@router.post("/ammo/objections", dependencies=[Depends(require_admin)])
async def create_objection(req: GenericModel):
    return {"objection": ammo_manager.create_objection(**req.fields)}


@router.patch("/ammo/objections/{item_id}", dependencies=[Depends(require_admin)])
async def update_objection(item_id: int, req: GenericModel):
    return {"objection": ammo_manager.update_objection(item_id, **req.fields)}

@router.delete("/ammo/objections/{item_id}", dependencies=[Depends(require_admin)])
async def delete_objection(item_id: int):
    return {"deleted": ammo_manager.delete_objection(item_id)}


@router.get("/ammo/competitors")
async def list_competitors(active_only: bool = Query(False), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"competitors": filter_by_tenant(ammo_manager.list_competitors(active_only=active_only), tenant_id)}


@router.post("/ammo/competitors", dependencies=[Depends(require_admin)])
async def create_competitor(req: GenericModel):
    return {"competitor": ammo_manager.create_competitor(**req.fields)}


@router.patch("/ammo/competitors/{item_id}", dependencies=[Depends(require_admin)])
async def update_competitor(item_id: int, req: GenericModel):
    return {"competitor": ammo_manager.update_competitor(item_id, **req.fields)}

@router.delete("/ammo/competitors/{item_id}", dependencies=[Depends(require_admin)])
async def delete_competitor(item_id: int):
    return {"deleted": ammo_manager.delete_competitor(item_id)}


@router.get("/ammo/scripts")
async def list_scripts(scene: str = Query(""), active_only: bool = Query(True), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"scripts": filter_by_tenant(ammo_manager.list_scripts(scene=scene, active_only=active_only), tenant_id)}


@router.post("/ammo/scripts", dependencies=[Depends(require_admin)])
async def create_script(req: GenericModel):
    return {"script": ammo_manager.create_script(**req.fields)}


@router.patch("/ammo/scripts/{item_id}", dependencies=[Depends(require_admin)])
async def update_script(item_id: int, req: GenericModel):
    return {"script": ammo_manager.update_script(item_id, **req.fields)}

@router.delete("/ammo/scripts/{item_id}", dependencies=[Depends(require_admin)])
async def delete_script(item_id: int):
    return {"deleted": ammo_manager.delete_script(item_id)}


@router.get("/ammo/cases")
async def list_cases(case_type: str = Query(""), keyword: str = Query(""), limit: int = Query(200, le=1000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"cases": filter_by_tenant(ammo_manager.list_cases(case_type=case_type, keyword=keyword, limit=limit), tenant_id)}


@router.post("/ammo/cases/analyze", dependencies=[Depends(require_admin)])
async def analyze_case(req: CaseImportModel):
    return ammo_manager.analyze_case(req.content, req.title)


@router.post("/ammo/cases/import", dependencies=[Depends(require_admin)])
async def import_case(req: CaseImportModel):
    return {"case": ammo_manager.import_case(req.content, req.title, req.channel)}

@router.delete("/ammo/cases/{item_id}", dependencies=[Depends(require_admin)])
async def delete_case(item_id: int):
    return {"deleted": ammo_manager.delete_case(item_id)}
