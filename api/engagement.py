"""业务工具接口：预约、优惠券、支付链接"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from core.tenant_scope import filter_by_tenant
from pydantic import BaseModel

from core.engagement import engagement_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["engagement"], dependencies=[Depends(require_api_key)])


class GenericModel(BaseModel):
    fields: dict = {}


class PaymentLinkModel(BaseModel):
    order_id: int
    title: str = ""
    amount: float = 0
    link: str = ""
    qr_text: str = ""
    session_id: str = ""
    valid_days: int = 7


@router.get("/appointments")
async def list_appointments(status: str = Query(""), limit: int = Query(200, le=1000)):
    return {"appointments": engagement_manager.list_appointments(status=status, limit=limit)}


@router.post("/appointments", dependencies=[Depends(require_admin)])
async def create_appointment(req: GenericModel):
    return {"appointment": engagement_manager.create_appointment(**req.fields)}


@router.patch("/appointments/{item_id}", dependencies=[Depends(require_admin)])
async def update_appointment(item_id: int, req: GenericModel):
    fields = req.fields
    return {"appointment": engagement_manager.update_appointment(item_id, fields.get("status", ""), fields.get("note", ""))}

@router.delete("/appointments/{item_id}", dependencies=[Depends(require_admin)])
async def delete_appointment(item_id: int):
    return {"deleted": engagement_manager.delete_appointment(item_id)}


@router.get("/coupons")
async def list_coupons(status: str = Query(""), limit: int = Query(200, le=1000)):
    return {"coupons": engagement_manager.list_coupons(status=status, limit=limit)}


@router.post("/coupons", dependencies=[Depends(require_admin)])
async def create_coupon(req: GenericModel):
    return {"coupon": engagement_manager.create_coupon(**req.fields)}


@router.patch("/coupons/{item_id}", dependencies=[Depends(require_admin)])
async def update_coupon(item_id: int, req: GenericModel):
    return {"coupon": engagement_manager.update_coupon(item_id, **req.fields)}

@router.delete("/coupons/{item_id}", dependencies=[Depends(require_admin)])
async def delete_coupon(item_id: int):
    return {"deleted": engagement_manager.delete_coupon(item_id)}


@router.post("/coupons/{coupon_id}/grant", dependencies=[Depends(require_admin)])
async def grant_coupon(coupon_id: int, req: GenericModel):
    fields = req.fields
    return {"user_coupon": engagement_manager.grant_coupon(
        coupon_id,
        session_id=fields.get("session_id", ""),
        customer_id=fields.get("customer_id"),
        lead_id=fields.get("lead_id"),
    )}


@router.get("/user-coupons")
async def list_user_coupons(session_id: str = Query(""), status: str = Query(""), limit: int = Query(200, le=1000)):
    return {"user_coupons": engagement_manager.list_user_coupons(session_id=session_id, status=status, limit=limit)}


@router.get("/payment-links")
async def list_payment_links(status: str = Query(""), limit: int = Query(200, le=1000)):
    return {"payment_links": engagement_manager.list_payment_links(status=status, limit=limit)}


@router.post("/payment-links", dependencies=[Depends(require_admin)])
async def create_payment_link(req: PaymentLinkModel):
    return {"payment_link": engagement_manager.create_payment_link(
        req.order_id, req.title, req.amount, req.link, req.qr_text,
        session_id=req.session_id, valid_days=req.valid_days,
    )}


@router.patch("/payment-links/{item_id}", dependencies=[Depends(require_admin)])
async def update_payment_link(item_id: int, req: GenericModel):
    fields = req.fields
    return {"payment_link": engagement_manager.update_payment_link(

        item_id, fields.get("status", ""), fields.get("link", ""), fields.get("qr_text", ""),
    )}

@router.delete("/payment-links/{item_id}", dependencies=[Depends(require_admin)])
async def delete_payment_link(item_id: int):
    return {"deleted": engagement_manager.delete_payment_link(item_id)}


@router.get("/engagement/stats")
async def engagement_stats():
    return engagement_manager.stats()
