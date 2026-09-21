"""CPQ：价目表、报价版本、折扣审批、合同条款与通用审批流"""
from __future__ import annotations
import json
import logging
from datetime import datetime

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import ApprovalFlow, Contract, PriceItem, Quote, QuoteLine

logger = logging.getLogger(__name__)

QUOTE_STATUSES = ["draft", "approving", "approved", "rejected", "sent", "accepted", "expired"]
CONTRACT_STATUSES = ["draft", "approving", "approved", "signed", "expired", "terminated"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _make_no(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{datetime.now().microsecond % 10000:04d}"


class CpqManager:
    def __init__(self):
        init_db()

    # ---------- 价目表 ----------
    def list_price_items(self, keyword: str = "", active_only: bool = False) -> list[dict]:
        with session_scope() as session:
            query = select(PriceItem).order_by(PriceItem.id.desc())
            if active_only:
                query = query.where(PriceItem.active.is_(True))
            if keyword:
                like = f"%{keyword}%"
                query = query.where(
                    PriceItem.product_name.like(like) | PriceItem.sku.like(like)
                )
            rows = session.execute(query).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def create_price_item(self, product_name, price, sku="", currency="CNY", description="") -> dict:
        with session_scope() as session:
            obj = PriceItem(
                product_name=product_name or "",
                sku=sku or "",
                price=float(price or 0),
                currency=currency or "CNY",
                active=True,
                description=description or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_price_item(self, price_item_id: int, **fields) -> dict | None:
        allowed = {"product_name", "sku", "price", "currency", "active", "description"}
        with session_scope() as session:
            obj = session.get(PriceItem, price_item_id)
            if not obj:
                return None
            for key, value in fields.items():
                if key in allowed and value is not None:
                    setattr(obj, key, value)
            obj.updated_at = _now()
            session.flush()
            return _row_to_dict(obj)

    # ---------- 报价 ----------
    def create_quote(
        self,
        customer_id=None,
        lead_id=None,
        session_id="",
        customer_name="",
        product_name="",
        base_amount=0,
        discount_rate=0,
        valid_until="",
        notes="",
        created_by="",
        lines=None,
    ) -> dict:
        version = self._next_version(session_id or customer_id or lead_id)
        discount_rate = max(0.0, min(100.0, float(discount_rate or 0)))
        base_amount = float(base_amount or 0)
        discount_amount = round(base_amount * discount_rate / 100.0, 2)
        total_amount = round(base_amount - discount_amount, 2)
        with session_scope() as session:
            obj = Quote(
                quote_no=_make_no("QT"),
                customer_id=customer_id,
                lead_id=lead_id,
                session_id=session_id or "",
                customer_name=customer_name or "",
                product_name=product_name or "",
                base_amount=base_amount,
                discount_rate=discount_rate,
                discount_amount=discount_amount,
                total_amount=total_amount,
                status="draft",
                version=version,
                valid_until=valid_until or "",
                notes=notes or "",
                created_by=created_by or "",
            )
            session.add(obj)
            session.flush()
            for line in lines or []:
                price = float(line.get("price") or 0)
                quantity = int(line.get("quantity") or 1)
                session.add(QuoteLine(
                    quote_id=obj.id,
                    product_name=line.get("product_name") or "",
                    price=price,
                    quantity=quantity,
                    amount=round(price * quantity, 2),
                ))
            quote_id = obj.id
        return self.get(quote_id)

    def _next_version(self, scope) -> int:
        if not scope:
            return 1
        with session_scope() as session:
            rows = session.execute(
                select(Quote).where(
                    (Quote.session_id == scope) |
                    (Quote.customer_id == scope if isinstance(scope, int) else Quote.customer_id.is_(None))
                )
            ).scalars().all()
            versions = [r.version or 1 for r in rows]
            return max(versions) + 1 if versions else 1

    def get(self, quote_id: int) -> dict | None:
        with session_scope() as session:
            obj = session.get(Quote, quote_id)
            if not obj:
                return None
            result = _row_to_dict(obj)
            result["lines"] = self._lines(session, quote_id)
            return result

    def list_quotes(self, status="", keyword="", limit=500) -> list[dict]:
        with session_scope() as session:
            query = select(Quote).order_by(Quote.id.desc())
            if status:
                query = query.where(Quote.status == status)
            if keyword:
                like = f"%{keyword}%"
                query = query.where(
                    Quote.quote_no.like(like) |
                    Quote.customer_name.like(like) |
                    Quote.product_name.like(like) |
                    Quote.session_id.like(like)
                )
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def change_quote_status(self, quote_id: int, status: str, comment: str = "", approver: str = "") -> dict | None:
        if status not in QUOTE_STATUSES:
            return None
        with session_scope() as session:
            obj = session.get(Quote, quote_id)
            if not obj:
                return None
            obj.status = status
            obj.updated_at = _now()
            session.flush()
            customer_id = obj.customer_id
            lead_id = obj.lead_id
            session_id = obj.session_id
            customer_name = obj.customer_name
            product_name = obj.product_name
            total_amount = obj.total_amount
            created_by = obj.created_by
        result = self.get(quote_id)

        if status in ("approving", "approved", "rejected"):
            self.create_approval(
                biz_type="quote",
                biz_id=quote_id,
                status="approved" if status == "approved" else "rejected" if status == "rejected" else "pending",
                approver=approver,
                comment=comment,
            )
        if status == "accepted":
            self.create_contract(
                quote_id=quote_id,
                customer_id=customer_id,
                lead_id=lead_id,
                session_id=session_id,
                customer_name=customer_name,
                product_name=product_name,
                amount=total_amount,
                created_by=created_by,
            )
        return result

    # ---------- 合同 ----------
    def create_contract(
        self,
        quote_id=None,
        customer_id=None,
        lead_id=None,
        session_id="",
        customer_name="",
        product_name="",
        amount=0,
        terms="",
        expires_at="",
        created_by="",
    ) -> dict:
        with session_scope() as session:
            obj = Contract(
                contract_no=_make_no("CT"),
                quote_id=quote_id,
                customer_id=customer_id,
                lead_id=lead_id,
                session_id=session_id or "",
                customer_name=customer_name or "",
                product_name=product_name or "",
                amount=float(amount or 0),
                status="draft",
                terms=terms or "",
                risk_level="low",
                expires_at=expires_at or "",
                created_by=created_by or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_contracts(self, status="", keyword="", limit=500) -> list[dict]:
        with session_scope() as session:
            query = select(Contract).order_by(Contract.id.desc())
            if status:
                query = query.where(Contract.status == status)
            if keyword:
                like = f"%{keyword}%"
                query = query.where(
                    Contract.contract_no.like(like) |
                    Contract.customer_name.like(like) |
                    Contract.product_name.like(like) |
                    Contract.session_id.like(like)
                )
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def change_contract_status(
        self,
        contract_id: int,
        status: str,
        signed_at: str = "",
        comment: str = "",
        approver: str = "",
    ) -> dict | None:
        if status not in CONTRACT_STATUSES:
            return None
        with session_scope() as session:
            obj = session.get(Contract, contract_id)
            if not obj:
                return None
            obj.status = status
            if status == "signed":
                obj.signed_at = signed_at or _now()
                obj.risk_level = "low"
            obj.updated_at = _now()
            session.flush()
            result = _row_to_dict(obj)

        if status in ("approving", "approved", "rejected"):
            self.create_approval(
                biz_type="contract",
                biz_id=contract_id,
                status="approved" if status == "approved" else "rejected" if status == "rejected" else "pending",
                approver=approver,
                comment=comment,
            )
        return result

    def refresh_contract_risk(self) -> dict:
        now = _now()
        with session_scope() as session:
            rows = session.execute(
                select(Contract).where(Contract.status.in_(["draft", "approving", "approved", "signed"]))
            ).scalars().all()
            updated = 0
            for obj in rows:
                risk = "low"
                reasons = []
                if obj.status in ("draft", "approving") and obj.signed_at == "":
                    risk = "high"
                    reasons.append("合同未签署")
                if obj.expires_at and obj.expires_at < now:
                    risk = "high" if risk == "low" else risk
                    reasons.append("合同已过期")
                if float(obj.amount or 0) <= 0:
                    risk = "high" if risk == "low" else risk
                    reasons.append("合同金额缺失")
                new_reason = "；".join(reasons)
                if risk != obj.risk_level or new_reason != obj.risk_reason:
                    obj.risk_level = risk
                    obj.risk_reason = new_reason
                    obj.updated_at = _now()
                    updated += 1
            return {"checked": len(rows), "updated": updated}

    # ---------- 审批流 ----------
    def create_approval(
        self,
        biz_type: str,
        biz_id: int,
        requester: str = "",
        approver: str = "",
        status: str = "pending",
        comment: str = "",
    ) -> dict:
        with session_scope() as session:
            obj = ApprovalFlow(
                biz_type=biz_type,
                biz_id=biz_id,
                requester=requester or "",
                approver=approver or "",
                status=status if status in ("pending", "approved", "rejected") else "pending",
                comment=comment or "",
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def list_approvals(self, biz_type="", status="", limit=500) -> list[dict]:
        with session_scope() as session:
            query = select(ApprovalFlow).order_by(ApprovalFlow.id.desc())
            if biz_type:
                query = query.where(ApprovalFlow.biz_type == biz_type)
            if status:
                query = query.where(ApprovalFlow.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def approve(self, approval_id: int, approver: str = "", comment: str = "", status: str = "approved") -> dict | None:
        with session_scope() as session:
            obj = session.get(ApprovalFlow, approval_id)
            if not obj:
                return None
            obj.status = status if status in ("approved", "rejected") else "approved"
            obj.approver = approver or obj.approver
            if comment:
                obj.comment = comment
            obj.updated_at = _now()
            session.flush()
            result = _row_to_dict(obj)
        if result["status"] == "approved":
            if result["biz_type"] == "quote":
                self.change_quote_status(result["biz_id"], "approved", approver=approver)
            elif result["biz_type"] == "contract":
                self.change_contract_status(result["biz_id"], "approved", approver=approver)
        return result

    def stats(self) -> dict:
        quotes = self.list_quotes(limit=100000)
        contracts = self.list_contracts(limit=100000)
        approvals = self.list_approvals(limit=100000)
        quote_status = {}
        contract_status = {}
        approval_status = {}
        quote_amount = 0.0
        contract_amount = 0.0
        for q in quotes:
            quote_status[q["status"]] = quote_status.get(q["status"], 0) + 1
            if q["status"] in ("approved", "sent", "accepted"):
                quote_amount += float(q.get("total_amount") or 0)
        for c in contracts:
            contract_status[c["status"]] = contract_status.get(c["status"], 0) + 1
            if c["status"] in ("approved", "signed"):
                contract_amount += float(c.get("amount") or 0)
        for a in approvals:
            approval_status[a["status"]] = approval_status.get(a["status"], 0) + 1
        return {
            "quotes": len(quotes),
            "quote_amount": round(quote_amount, 2),
            "quote_status": quote_status,
            "contracts": len(contracts),
            "contract_amount": round(contract_amount, 2),
            "contract_status": contract_status,
            "approvals_pending": approval_status.get("pending", 0),
            "approvals": len(approvals),
            "approval_status": approval_status,
        }

    @staticmethod
    def _lines(session, quote_id: int) -> list[dict]:
        rows = session.execute(
            select(QuoteLine).where(QuoteLine.quote_id == quote_id)
        ).scalars().all()
        return [_row_to_dict(r) for r in rows]


cpq_manager = CpqManager()
