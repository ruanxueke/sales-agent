"""销售线索接口：批量导入、公海池、分配认领、跟进与状态流转"""
from __future__ import annotations
import logging

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from config.settings import settings
from core.lead import LEAD_STATUSES, lead_manager, parse_import_file, template_csv
from core.security import current_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["leads"])


class LeadCreate(BaseModel):
    session_id: str = ""
    name: str = ""
    phone: str = ""
    wechat_id: str = ""
    unionid: str = ""
    nickname: str = ""
    source: str = "import"
    channel_id: str = ""
    identity: str = ""
    level: str = ""
    goal: str = ""
    budget: str = ""
    interest: str = ""
    intent_level: str = ""
    intent_score: int = 0
    status: str = ""
    owner: str = ""
    notes: str = ""
    next_follow_up: str = ""


class LeadUpdate(BaseModel):
    session_id: str = ""
    name: str = ""
    phone: str = ""
    wechat_id: str = ""
    unionid: str = ""
    nickname: str = ""
    source: str = ""
    channel_id: str = ""
    identity: str = ""
    level: str = ""
    goal: str = ""
    budget: str = ""
    interest: str = ""
    intent_level: str = ""
    intent_score: int = 0
    status: str = ""
    owner: str = ""
    notes: str = ""
    next_follow_up: str = ""


class OwnerRequest(BaseModel):
    owner: str = ""


class FollowRequest(BaseModel):
    owner: str = ""
    note: str = ""
    next_follow_up: str = ""


class StatusRequest(BaseModel):
    status: str


@router.get("/leads")
async def list_leads(
    request: Request,
    status: str = Query(""),
    owner: str = Query(""),
    source: str = Query(""),
    keyword: str = Query(""),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    return {"leads": lead_manager.list(
        status=status,
        owner=owner,
        source=source,
        keyword=keyword,
        limit=limit,
        offset=offset,
        tenant_id=current_tenant(request),
    )}


@router.get("/leads/ocean")
async def list_ocean(request: Request, limit: int = Query(500, ge=1, le=2000)):
    return {
        "leads": lead_manager.list(
            status="pending",
            limit=limit,
            tenant_id=current_tenant(request),
        )
    }


@router.get("/leads/stats")
async def lead_stats(request: Request):
    return lead_manager.stats(tenant_id=current_tenant(request))


@router.get("/leads/import/template")
async def download_template():
    content = template_csv()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads_template.csv"},
    )


@router.post("/leads/import")
async def import_leads(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    rows, parse_errors = parse_import_file(file.filename or "", content)
    if len(rows) > settings.LEAD_IMPORT_MAX_ROWS:
        return {
            "ok": False,
            "total": len(rows),
            "created": 0,
            "updated": 0,
            "failed": len(rows),
            "errors": [{"row": 1, "reason": f"单次最多导入 {settings.LEAD_IMPORT_MAX_ROWS} 条"}],
        }
    result = lead_manager.import_rows(
        rows,
        tenant_id=current_tenant(request),
    )
    result["ok"] = len(parse_errors) == 0
    result["errors"] = parse_errors + result["errors"]
    result["failed"] = len(result["errors"])
    return result


@router.post("/leads")
async def create_lead(req: LeadCreate, request: Request):
    data = req.model_dump(exclude_unset=True)
    return {
        "lead": lead_manager.create(
            data,
            tenant_id=current_tenant(request),
        )
    }


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: int, request: Request):
    return {
        "lead": lead_manager.get(
            lead_id,
            tenant_id=current_tenant(request),
        )
    }


@router.patch("/leads/{lead_id}")
async def update_lead(lead_id: int, req: LeadUpdate, request: Request):
    data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    lead = lead_manager.update(
        lead_id,
        tenant_id=current_tenant(request),
        **data,
    )
    if not lead:
        return {"lead": None}
    return {"lead": lead}


@router.post("/leads/{lead_id}/assign")
async def assign_lead(lead_id: int, req: OwnerRequest, request: Request):
    lead = lead_manager.assign(
        lead_id,
        req.owner,
        tenant_id=current_tenant(request),
    )
    if not lead:
        return {"lead": None}
    return {"lead": lead}


@router.post("/leads/{lead_id}/claim")
async def claim_lead(lead_id: int, req: OwnerRequest, request: Request):
    lead = lead_manager.claim(
        lead_id,
        req.owner,
        tenant_id=current_tenant(request),
    )
    if not lead:
        return {"lead": None}
    return {"lead": lead}


@router.post("/leads/{lead_id}/follow")
async def follow_lead(lead_id: int, req: FollowRequest, request: Request):
    lead = lead_manager.follow(
        lead_id,
        owner=req.owner,
        note=req.note,
        next_follow_up=req.next_follow_up,
        tenant_id=current_tenant(request),
    )
    if not lead:
        return {"lead": None}
    return {"lead": lead}


@router.post("/leads/{lead_id}/status")
async def change_lead_status(lead_id: int, req: StatusRequest, request: Request):
    if req.status not in LEAD_STATUSES:
        return {"lead": None, "error": f"未知状态: {req.status}"}
    lead = lead_manager.mark_status(
        lead_id,
        req.status,
        tenant_id=current_tenant(request),
    )
    if not lead:
        return {"lead": None}
    return {"lead": lead}


@router.post("/leads/recycle")
async def recycle_leads(request: Request):
    count = lead_manager.recycle(tenant_id=current_tenant(request))
    return {"recycled": count}
