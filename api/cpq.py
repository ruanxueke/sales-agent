"""报价、合同、价目表与审批流接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.cpq import cpq_manager
from core.security import require_admin, require_api_key
import logging
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1", tags=["cpq"], dependencies=[Depends(require_api_key)])


class PriceItemCreate(BaseModel):
    product_name: str
    price: float = 0
    sku: str = ""
    currency: str = "CNY"
    description: str = ""


class PriceItemUpdate(BaseModel):
    product_name: str = ""
    sku: str = ""
    price: float = None
    currency: str = ""
    active: bool = None
    description: str = ""


class QuoteCreate(BaseModel):
    customer_id: int = None
    lead_id: int = None
    session_id: str = ""
    customer_name: str = ""
    product_name: str = ""
    base_amount: float = 0
    discount_rate: float = 0
    valid_until: str = ""
    notes: str = ""
    created_by: str = ""
    lines: list[dict] = []


class QuoteStatus(BaseModel):
    status: str
    comment: str = ""
    approver: str = ""


class ContractCreate(BaseModel):
    quote_id: int = None
    customer_id: int = None
    lead_id: int = None
    session_id: str = ""
    customer_name: str = ""
    product_name: str = ""
    amount: float = 0
    terms: str = ""
    expires_at: str = ""
    created_by: str = ""


class ContractStatus(BaseModel):
    status: str
    signed_at: str = ""
    comment: str = ""
    approver: str = ""


class ApprovalRequest(BaseModel):
    status: str = "approved"
    approver: str = ""
    comment: str = ""


@router.get("/price-items")
async def list_price_items(keyword: str = Query(""), active_only: bool = Query(False)):
    return {"items": cpq_manager.list_price_items(keyword=keyword, active_only=active_only)}


@router.post("/price-items", dependencies=[Depends(require_admin)])
async def create_price_item(req: PriceItemCreate):
    return {"item": cpq_manager.create_price_item(**req.model_dump())}


@router.patch("/price-items/{item_id}", dependencies=[Depends(require_admin)])
async def update_price_item(item_id: int, req: PriceItemUpdate):
    data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    return {"item": cpq_manager.update_price_item(item_id, **data)}


@router.get("/quotes")
async def list_quotes(status: str = Query(""), keyword: str = Query(""), limit: int = Query(500, le=2000)):
    return {"quotes": cpq_manager.list_quotes(status=status, keyword=keyword, limit=limit)}


@router.get("/quotes/{quote_id}")
async def get_quote(quote_id: int):
    return {"quote": cpq_manager.get(quote_id)}


@router.post("/quotes", dependencies=[Depends(require_admin)])
async def create_quote(req: QuoteCreate):
    quote = cpq_manager.create_quote(**req.model_dump())
    try:
        from core.enterprise import enterprise
        for rule in enterprise.check_approval_rules(
            "quote", {"discount_rate": quote.get("discount_rate") or 0, "amount": quote.get("total_amount") or 0}
        ):
            enterprise.create_approval("quote", quote["id"], rule)
    except Exception as e:
        logger.warning("报价审批单创建失败，审批流程静默缺失: %s", e)
    return {"quote": quote}


@router.post("/quotes/{quote_id}/status", dependencies=[Depends(require_admin)])
async def change_quote_status(quote_id: int, req: QuoteStatus):
    return {"quote": cpq_manager.change_quote_status(quote_id, req.status, req.comment, req.approver)}


@router.get("/contracts")
async def list_contracts(status: str = Query(""), keyword: str = Query(""), limit: int = Query(500, le=2000)):
    return {"contracts": cpq_manager.list_contracts(status=status, keyword=keyword, limit=limit)}


@router.post("/contracts", dependencies=[Depends(require_admin)])
async def create_contract(req: ContractCreate):
    contract = cpq_manager.create_contract(**req.model_dump())
    try:
        from core.enterprise import enterprise
        for rule in enterprise.check_approval_rules(
            "contract", {"amount": contract.get("amount") or 0}
        ):
            enterprise.create_approval("contract", contract["id"], rule)
    except Exception as e:
        logger.warning("合同审批单创建失败，审批流程静默缺失: %s", e)
    return {"contract": contract}


@router.post("/contracts/{contract_id}/status", dependencies=[Depends(require_admin)])
async def change_contract_status(contract_id: int, req: ContractStatus):
    return {"contract": cpq_manager.change_contract_status(
        contract_id, req.status, req.signed_at, req.comment, req.approver,
    )}


@router.post("/contracts/refresh-risk", dependencies=[Depends(require_admin)])
async def refresh_contract_risk():
    return cpq_manager.refresh_contract_risk()


@router.get("/approvals")
async def list_approvals(biz_type: str = Query(""), status: str = Query(""), limit: int = Query(500, le=2000)):
    return {"approvals": cpq_manager.list_approvals(biz_type=biz_type, status=status, limit=limit)}


@router.post("/approvals/{approval_id}/decide", dependencies=[Depends(require_admin)])
async def decide_approval(approval_id: int, req: ApprovalRequest):
    return {"approval": cpq_manager.approve(approval_id, req.approver, req.comment, req.status)}


@router.get("/cpq/stats")
async def cpq_stats():
    return cpq_manager.stats()
