"""数据导出：客户、线索、订单、质检 CSV"""
from __future__ import annotations
import csv
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from core.security import current_tenant, permission_required, require_api_key
from core.tenant_scope import filter_by_tenant

router = APIRouter(
    prefix="/api/v1",
    tags=["export"],
    dependencies=[
        Depends(require_api_key),
        Depends(permission_required("data:export")),
    ],
)


def _csv_response(filename: str, headers: list[str], rows: list[dict]) -> Response:
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h, "") for h in headers])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _visible_rows(request: Request, rows: list[dict]) -> list[dict]:
    return filter_by_tenant(rows, current_tenant(request))


@router.get("/export/customers.csv")
async def export_customers(request: Request):
    from core.sales_crm import crm
    customers = crm.list_customers(tenant_id=current_tenant(request))
    headers = [
        "id", "session_id", "nickname", "name", "phone", "wechat_id",
        "identity", "level", "goal", "budget", "interest", "stage",
        "intent_level", "intent_score", "source", "next_follow_up",
        "created_at", "updated_at",
    ]
    return _csv_response("customers.csv", headers, customers)


@router.get("/export/leads.csv")
async def export_leads(request: Request):
    from core.lead import lead_manager
    leads = lead_manager.list(limit=100000)
    headers = [
        "id", "session_id", "name", "nickname", "phone", "wechat_id",
        "unionid", "source", "channel_id", "goal", "budget", "interest",
        "intent_level", "stage", "status", "owner", "next_follow_up",
        "created_at", "updated_at",
    ]
    return _csv_response("leads.csv", headers, _visible_rows(request, leads))


@router.get("/export/orders.csv")
async def export_orders(request: Request):
    from core.order import order_manager
    orders = order_manager.list_orders(limit=100000)
    headers = [
        "id", "order_no", "customer_id", "lead_id", "session_id",
        "customer_name", "phone", "product_name", "amount", "status",
        "pay_method", "paid_at", "created_at",
    ]
    return _csv_response("orders.csv", headers, _visible_rows(request, orders))


@router.get("/export/quality.csv")
async def export_quality(request: Request):
    from core.quality import quality_checker
    reports = quality_checker.list_reports(limit=100000)
    headers = [
        "id", "customer_id", "session_id", "score", "sop_score",
        "tone_score", "issues", "created_at",
    ]
    return _csv_response("quality.csv", headers, _visible_rows(request, reports))


@router.get("/export/opportunities.csv")
async def export_opportunities(request: Request):
    from core.opportunity import opportunity_manager
    rows = opportunity_manager.list(limit=100000)
    headers = [
        "id", "name", "session_id", "customer_id", "lead_id", "product_name",
        "amount", "stage", "win_rate", "owner", "expected_close_at",
        "risk_level", "loss_reason", "created_at", "updated_at",
    ]
    return _csv_response("opportunities.csv", headers, _visible_rows(request, rows))


@router.get("/export/quotes.csv")
async def export_quotes(request: Request):
    from core.cpq import cpq_manager
    rows = cpq_manager.list_quotes(limit=100000)
    headers = [
        "id", "quote_no", "session_id", "customer_name", "product_name",
        "base_amount", "discount_rate", "total_amount", "status", "version",
        "valid_until", "created_by", "created_at",
    ]
    return _csv_response("quotes.csv", headers, _visible_rows(request, rows))


@router.get("/export/contracts.csv")
async def export_contracts(request: Request):
    from core.cpq import cpq_manager
    rows = cpq_manager.list_contracts(limit=100000)
    headers = [
        "id", "contract_no", "quote_id", "session_id", "customer_name",
        "product_name", "amount", "status", "risk_level", "signed_at",
        "expires_at", "created_at",
    ]
    return _csv_response("contracts.csv", headers, _visible_rows(request, rows))


@router.get("/export/receivables.csv")
async def export_receivables(request: Request):
    from core.finance import finance_manager
    rows = finance_manager.list_receivables(limit=100000)
    headers = [
        "id", "order_id", "plan_id", "amount", "received_amount",
        "status", "due_at", "last_received_at", "created_at",
    ]
    return _csv_response("receivables.csv", headers, _visible_rows(request, rows))


@router.get("/export/tickets.csv")
async def export_tickets(request: Request):
    from core.ticket import ticket_manager
    rows = ticket_manager.list_tickets(limit=100000)
    headers = [
        "id", "ticket_no", "session_id", "customer_id", "lead_id", "title",
        "priority", "category", "status", "owner", "sla_due_at",
        "resolved_at", "created_at",
    ]
    return _csv_response("tickets.csv", headers, _visible_rows(request, rows))


@router.get("/export/campaigns.csv")
async def export_campaigns(request: Request):
    from core.marketing import marketing_manager
    rows = marketing_manager.list_campaigns(limit=100000)
    headers = [
        "id", "name", "channel", "status", "budget", "cost",
        "start_at", "end_at", "target", "created_at",
    ]
    return _csv_response("campaigns.csv", headers, _visible_rows(request, rows))


@router.get("/export/team.csv")
async def export_team(request: Request):
    from core.platform import platform_manager
    rows = platform_manager.list_members()
    headers = [
        "id", "tenant_id", "name", "nickname", "role", "phone",
        "email", "status", "created_at",
    ]
    return _csv_response("team.csv", headers, _visible_rows(request, rows))
