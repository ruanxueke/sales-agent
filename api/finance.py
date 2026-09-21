"""回款与 L2C 接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.finance import finance_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["finance"], dependencies=[Depends(require_api_key)])


class ShipmentCreate(BaseModel):
    order_id: int
    tracking_no: str = ""
    carrier: str = ""
    address: str = ""


class ShipmentUpdate(BaseModel):
    status: str = ""
    tracking_no: str = ""
    carrier: str = ""


class InvoiceCreate(BaseModel):
    order_id: int
    amount: float = 0
    title: str = ""
    tax_no: str = ""


class InvoiceStatus(BaseModel):
    status: str


class PlanCreate(BaseModel):
    order_id: int
    amounts: list[float] = []
    due_dates: list[str] = []


class ReceiptCreate(BaseModel):
    amount: float
    method: str = "transfer"
    transaction_id: str = ""


@router.get("/shipments")
async def list_shipments(status: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"shipments": filter_by_tenant(finance_manager.list_shipments(status=status, limit=limit), tenant_id)}


@router.post("/shipments", dependencies=[Depends(require_admin)])
async def create_shipment(req: ShipmentCreate):
    return {"shipment": finance_manager.create_shipment(**req.model_dump())}


@router.patch("/shipments/{shipment_id}", dependencies=[Depends(require_admin)])
async def update_shipment(shipment_id: int, req: ShipmentUpdate):
    return {"shipment": finance_manager.update_shipment(
        shipment_id, status=req.status, tracking_no=req.tracking_no, carrier=req.carrier,
    )}


@router.get("/invoices")
async def list_invoices(status: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"invoices": filter_by_tenant(finance_manager.list_invoices(status=status, limit=limit), tenant_id)}


@router.post("/invoices", dependencies=[Depends(require_admin)])
async def create_invoice(req: InvoiceCreate):
    return {"invoice": finance_manager.create_invoice(**req.model_dump())}


@router.post("/invoices/{invoice_id}/status", dependencies=[Depends(require_admin)])
async def change_invoice_status(invoice_id: int, req: InvoiceStatus):
    return {"invoice": finance_manager.change_invoice_status(invoice_id, req.status)}


@router.get("/payment-plans")
async def list_payment_plans(order_id: int = Query(0), status: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"plans": filter_by_tenant(finance_manager.list_payment_plans(order_id=order_id, status=status, limit=limit), tenant_id)}


@router.post("/payment-plans", dependencies=[Depends(require_admin)])
async def create_payment_plans(req: PlanCreate):
    return finance_manager.create_payment_plans(req.order_id, req.amounts, req.due_dates)


@router.get("/receivables")
async def list_receivables(status: str = Query(""), limit: int = Query(500, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"receivables": filter_by_tenant(finance_manager.list_receivables(status=status, limit=limit), tenant_id)}


@router.post("/receivables/{receivable_id}/receipt", dependencies=[Depends(require_admin)])
async def record_receipt(receivable_id: int, req: ReceiptCreate):
    return {"receivable": finance_manager.record_receipt(
        receivable_id, req.amount, req.method, req.transaction_id,
    )}


@router.post("/finance/refresh-overdue", dependencies=[Depends(require_admin)])
async def refresh_overdue():
    return finance_manager.refresh_overdue()


@router.get("/finance/stats")
async def finance_stats():
    return finance_manager.stats()
