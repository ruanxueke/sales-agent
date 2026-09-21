"""审计日志查询接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request

from core.audit import list_audit
from core.security import current_tenant, require_admin

router = APIRouter(prefix="/api/v1", tags=["audit"], dependencies=[Depends(require_admin)])


@router.get("/audit")
async def audit_logs(
    request: Request,
    limit: int = Query(200, le=2000),
    level: str = Query(""),
    category: str = Query(""),
):
    return {
        "logs": list_audit(
            limit=limit,
            level=level,
            category=category,
            tenant_id=current_tenant(request),
        )
    }
