"""支付回调接口：检测付款成功后自动推送交付文档"""
from __future__ import annotations
import logging

from fastapi import APIRouter, Request

from config.settings import settings
from core.order import order_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["payment"])


def _lookup(payload: dict, *keys, default=""):
    for k in keys:
        v = payload.get(k)
        if v not in (None, ""):
            return v
    order_info = payload.get("orderInfo") or payload.get("order_info") or {}
    if isinstance(order_info, dict):
        for k in keys:
            v = order_info.get(k)
            if v not in (None, ""):
                return v
    return default


def _is_paid(payload: dict) -> bool:
    event = str(_lookup(payload, "event", "type", "status", "pay_status", "paid")).upper()
    if any(k in event for k in ("PAID", "SUCCESS", "DONE")):
        return True
    return str(_lookup(payload, "paid", default="")).lower() in ("true", "1", "yes")


@router.post("/payment/webhook")
async def payment_webhook(request: Request, payload: dict):
    """付款成功回调。

    支持常见字段：session_id/openid、order_id/order_no、amount、transaction_id。
    小鹅通等平台可把回调地址配置为 POST http://服务器/api/v1/payment/webhook。
    """
    secret = settings.PAYMENT_WEBHOOK_SECRET or ""
    if not secret and not settings.ALLOW_UNSIGNED_PAYMENT_WEBHOOK:
        return {
            "ok": False,
            "error": "支付回调密钥未配置，已拒绝未验签请求",
        }
    if secret:
        provided = request.headers.get("X-Pay-Secret") or str(_lookup(payload, "secret") or "")
        if provided != secret:
            return {"ok": False, "error": "invalid secret"}

    if not _is_paid(payload):
        return {"ok": True, "handled": False}

    session_id = str(_lookup(payload, "session_id", "openid", "touser", "from_user", "customer_openid") or "")
    order_id = _lookup(payload, "order_id", "orderId", "out_trade_no")
    order_no = str(_lookup(payload, "order_no", "orderNo") or "")
    amount = float(_lookup(payload, "amount", "total_fee", "pay_amount", default=0) or 0)
    transaction_id = str(_lookup(payload, "transaction_id", "trade_no", "payment_no") or "")
    method = str(_lookup(payload, "pay_method", "method", default="wechat") or "wechat")

    order = None
    if order_id:
        try:
            order = order_manager.pay_order(int(order_id), method=method, transaction_id=transaction_id)
        except Exception as e:
            logger.error(f"支付回调按 order_id 处理失败: {e}")

    if order is None and order_no:
        try:
            for o in order_manager.list_orders(limit=100000):
                if o.get("order_no") == order_no:
                    order = order_manager.pay_order(o["id"], method=method, transaction_id=transaction_id)
                    break
        except Exception as e:
            logger.error(f"支付回调按 order_no 处理失败: {e}")

    if order is None and transaction_id:
        try:
            for p in order_manager.list_payments(limit=100000):
                if p.get("transaction_id") == transaction_id:
                    order = order_manager.pay_order(p["order_id"], method=method, transaction_id=transaction_id)
                    break
        except Exception as e:
            logger.error(f"支付回调按 transaction_id 处理失败: {e}")

    if order is None:
        product = str(_lookup(payload, "product_name", "title") or "赵焱AI赋能实战课（无社群）")
        try:
            order = order_manager.create_order(
                session_id=session_id,
                customer_name=session_id,
                product_name=product,
                amount=amount,
            )
            order = order_manager.pay_order(order["id"], method=method, transaction_id=transaction_id)
        except Exception as e:
            logger.error(f"支付回调自动建单失败: {e}")
            return {"ok": False, "error": str(e)}

    return {"ok": True, "handled": True, "order_id": (order or {}).get("id")}
