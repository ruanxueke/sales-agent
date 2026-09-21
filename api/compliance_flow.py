"""合规接口：授权留存、数据删除请求与执行"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from core.compliance_flow import compliance_flow
from core.privacy import privacy_status, purge_expired_chat
from core.security import (
    current_tenant,
    permission_required,
    require_admin,
    require_api_key,
)

router = APIRouter(prefix="/api/v1", tags=["compliance"])


class ConsentCreate(BaseModel):
    session_id: str
    source: str = ""
    content: str = ""


class DeletionCreate(BaseModel):
    session_id: str
    applicant: str = ""
    reason: str = ""


@router.get(
    "/compliance/consents",
    dependencies=[Depends(permission_required("customer:read"))],
)
async def list_consents(
    request: Request,
    session_id: str = Query(""),
    limit: int = Query(200, le=1000),
):
    return {
        "items": compliance_flow.list_consents(
            session_id=session_id,
            limit=limit,
            tenant_id=current_tenant(request),
        )
    }


@router.post("/compliance/consent", dependencies=[Depends(require_admin)])
async def add_consent(req: ConsentCreate, request: Request):
    return {
        "item": compliance_flow.add_consent(
            req.session_id,
            req.source,
            req.content,
            tenant_id=current_tenant(request),
        )
    }


@router.post("/compliance/deletion-request")
async def request_deletion(req: DeletionCreate, request: Request):
    return {
        "item": compliance_flow.request_deletion(
            req.session_id,
            req.applicant,
            req.reason,
            tenant_id=current_tenant(request),
        )
    }


@router.get("/compliance/deletion-requests", dependencies=[Depends(require_admin)])
async def list_deletion_requests(
    request: Request,
    status: str = Query(""),
    limit: int = Query(200, le=1000),
):
    return {
        "items": compliance_flow.list_deletion_requests(
            status=status,
            limit=limit,
            tenant_id=current_tenant(request),
        )
    }


@router.post("/compliance/deletion-requests/{request_id}/confirm", dependencies=[Depends(require_admin)])
async def confirm_deletion(request_id: int, request: Request):
    return compliance_flow.confirm_deletion(
        request_id,
        tenant_id=current_tenant(request),
    )


@router.get("/compliance/status")
async def compliance_status(request: Request, session_id: str = Query("")):
    return compliance_flow.compliance_status(
        session_id,
        tenant_id=current_tenant(request),
    )


@router.get(
    "/compliance/privacy-status",
    dependencies=[Depends(require_admin)],
)
async def get_privacy_status(request: Request):
    return privacy_status(tenant_id=current_tenant(request))


@router.post(
    "/compliance/retention/run",
    dependencies=[Depends(require_admin)],
)
async def run_retention_cleanup(request: Request):
    return purge_expired_chat(tenant_id=current_tenant(request))
