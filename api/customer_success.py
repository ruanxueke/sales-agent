"""客户成功 API：租户健康度、续费预警、CSM 总览"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from core.customer_success import csm_overview, renewal_alerts, tenant_health
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["customer-success"], dependencies=[Depends(require_api_key)])


@router.get("/customer-success/overview", dependencies=[Depends(require_admin)])
async def overview():
    return csm_overview()


@router.get("/customer-success/health", dependencies=[Depends(require_admin)])
async def health(tenant_id: int = Query(0)):
    return {"health": tenant_health(tenant_id or None)}


@router.get("/customer-success/renewal-alerts", dependencies=[Depends(require_admin)])
async def alerts():
    return {"items": renewal_alerts()}
