"""计费 API：套餐、订阅、用量、账单（外部支付网关占位）"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.billing import PLANS, billing
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["billing"], dependencies=[Depends(require_api_key)])


class SubscribeModel(BaseModel):
    tenant_id: int
    plan: str
    days: int = 30


class InvoicePaidModel(BaseModel):
    invoice_id: int
    provider: str = ""
    trade_no: str = ""


@router.get("/billing/plans")
async def plans():
    return {"plans": PLANS}


@router.get("/billing/health")
async def health():
    return billing.health()


@router.get("/billing/subscription")
async def subscription(tenant_id: int):
    return {"subscription": billing.get_subscription(tenant_id), "usage_30d": billing.usage(tenant_id)}


@router.post("/billing/subscribe", dependencies=[Depends(require_admin)])
async def subscribe(req: SubscribeModel):
    try:
        sub = billing.subscribe(req.tenant_id, req.plan, req.days)
        invoice = billing.create_invoice(req.tenant_id, req.plan)
        return {"ok": True, "subscription": sub, "invoice": invoice, "payment_required": invoice["amount"] > 0}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.post("/billing/cancel", dependencies=[Depends(require_admin)])
async def cancel(tenant_id: int):
    return {"ok": billing.cancel(tenant_id)}


@router.post("/billing/invoices/paid", dependencies=[Depends(require_admin)])
async def mark_paid(req: InvoicePaidModel):
    return {"ok": billing.mark_paid(req.invoice_id, req.provider, req.trade_no)}


@router.get("/billing/invoices")
async def invoices(tenant_id: int = 0):
    return {"items": billing.list_invoices(tenant_id)}
