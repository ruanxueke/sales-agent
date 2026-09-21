"""企业级数据智能 API：经营总览、漏斗、ROI、趋势、团队、自定义报表与 CSV 导出"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from core.business_intelligence import (
    create_report,
    delete_report,
    export_csv,
    funnel,
    list_reports,
    overview,
    report_meta,
    roi,
    run_report,
    team,
    trends,
)
from core.security import current_tenant, require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["business-intelligence"], dependencies=[Depends(require_api_key)])


class ReportCreate(BaseModel):
    name: str = ""
    metric: str = "customers"
    dimension: str = "date"
    days: int = 30
    filters: dict = {}
    created_by: str = ""


class ReportRun(BaseModel):
    report_id: int = 0
    name: str = ""
    metric: str = "customers"
    dimension: str = "date"
    days: int = 30
    filters: dict = {}


def _tenant(request: Request):
    return current_tenant(request)


@router.get("/bi/overview")
async def bi_overview(days: int = Query(7, ge=1, le=365), request: Request = None):
    return overview(current_tenant(request), days)


@router.get("/bi/funnel")
async def bi_funnel(days: int = Query(30, ge=1, le=365), request: Request = None):
    return funnel(current_tenant(request), days)


@router.get("/bi/roi")
async def bi_roi(days: int = Query(30, ge=1, le=365), request: Request = None):
    return roi(current_tenant(request), days)


@router.get("/bi/trends")
async def bi_trends(days: int = Query(30, ge=1, le=90), request: Request = None):
    return trends(current_tenant(request), days)


@router.get("/bi/team")
async def bi_team(days: int = Query(30, ge=1, le=365), request: Request = None):
    return team(current_tenant(request), days)


@router.get("/bi/reports/meta")
async def bi_report_meta():
    return report_meta()


@router.get("/bi/reports")
async def bi_reports(request: Request = None):
    return {"items": list_reports(current_tenant(request))}


@router.post("/bi/reports", dependencies=[Depends(require_admin)])
async def bi_create_report(req: ReportCreate, request: Request = None):
    try:
        report = create_report(
            current_tenant(request),
            req.name,
            req.metric,
            req.dimension,
            req.days,
            req.filters,
            req.created_by,
        )
        return {"ok": True, "report": report}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.delete("/bi/reports/{report_id}", dependencies=[Depends(require_admin)])
async def bi_delete_report(report_id: int, request: Request = None):
    return {"ok": delete_report(report_id, current_tenant(request))}


@router.post("/bi/reports/run")
async def bi_run_report(req: ReportRun, request: Request = None):
    if req.report_id:
        saved = next((r for r in list_reports(current_tenant(request)) if r.get("id") == req.report_id), None)
        if not saved:
            return {"ok": False, "error": "报表不存在或无权访问"}
        return run_report(saved, current_tenant(request))
    return run_report(req.model_dump(), current_tenant(request))


@router.get("/bi/export")
async def bi_export(
    name: str = "",
    metric: str = Query("customers"),
    dimension: str = Query("date"),
    days: int = Query(30, ge=1, le=365),
    request: Request = None,
):
    report = {"name": name, "metric": metric, "dimension": dimension, "days": days}
    content = export_csv(report, current_tenant(request))
    if not content:
        return Response(content="", media_type="text/csv")
    filename = f"bi_{metric}_{dimension}_{days}d.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
