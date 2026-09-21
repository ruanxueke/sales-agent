"""报表查询接口：转化、跟进提醒、数据看板"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request

from core.reports import conversion, dashboard, followups
from core.security import current_tenant, permission_required

router = APIRouter(
    prefix="/api/v1",
    tags=["reports"],
    dependencies=[Depends(permission_required("report:read"))],
)


@router.get("/reports/conversion")
async def reports_conversion(request: Request, days: int = 30):
    return conversion(days, tenant_id=current_tenant(request))


@router.get("/reports/followups")
async def reports_followups(request: Request, limit: int = 200):
    return followups(limit, tenant_id=current_tenant(request))


@router.get("/reports/dashboard")
async def reports_dashboard(request: Request, days: int = 7):
    return dashboard(days, tenant_id=current_tenant(request))
