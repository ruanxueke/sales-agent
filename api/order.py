"""订单、支付、售后接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Query
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.order import order_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["orders"], dependencies=[Depends(require_api_key)])


class OrderCreate(BaseModel):
    customer_id: int = None
    lead_id: int = None
    session_id: str = ""
    customer_name: str = ""
    phone: str = ""
    product_name: str = ""
    amount: float = 0
    status: str = "draft"


class PayRequest(BaseModel):
    method: str = ""
    transaction_id: str = ""


class AfterSaleCreate(BaseModel):
    reason: str
    handler: str = ""


class AfterSaleUpdate(BaseModel):
    status: str
    handler: str = ""


@router.get("/orders")
async def list_orders(status: str = Query(""), limit: int = Query(200, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"orders": filter_by_tenant(order_manager.list_orders(status=status, limit=limit), tenant_id)}


@router.get("/orders/stats")
async def order_stats():
    return order_manager.stats()


@router.get("/payments")
async def list_payments(limit: int = Query(200, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"payments": filter_by_tenant(order_manager.list_payments(limit=limit), tenant_id)}


@router.get("/after-sales")
async def list_after_sales(status: str = Query(""), limit: int = Query(200, le=2000), request: Request = None):
    from core.security import current_tenant
    tenant_id = current_tenant(request)
    return {"after_sales": filter_by_tenant(order_manager.list_after_sales(status=status, limit=limit), tenant_id)}


@router.post("/orders", dependencies=[Depends(require_admin)])
async def create_order(req: OrderCreate):
    order = order_manager.create_order(**req.model_dump())
    return {"order": order}


@router.post("/orders/{order_id}/pay", dependencies=[Depends(require_admin)])
async def pay_order(order_id: int, req: PayRequest):
    order = order_manager.pay_order(order_id, method=req.method, transaction_id=req.transaction_id)
    if not order:
        return {"order": None}
    return {"order": order}


@router.post("/orders/{order_id}/after-sale", dependencies=[Depends(require_admin)])
async def create_after_sale(order_id: int, req: AfterSaleCreate):
    after_sale = order_manager.create_after_sale(order_id, reason=req.reason, handler=req.handler)
    if not after_sale:
        return {"after_sale": None}
    return {"after_sale": after_sale}


@router.patch("/after-sales/{after_sale_id}", dependencies=[Depends(require_admin)])
async def update_after_sale(after_sale_id: int, req: AfterSaleUpdate):
    after_sale = order_manager.update_after_sale(after_sale_id, req.status, req.handler)
    if not after_sale:
        return {"after_sale": None}
    return {"after_sale": after_sale}
