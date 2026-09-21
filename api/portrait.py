"""360° 客户画像接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.portrait import portrait_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["portrait"], dependencies=[Depends(require_api_key)])


class BusinessProfileModel(BaseModel):
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None
    company_name: str = ""
    unified_code: str = ""
    legal_person: str = ""
    registered_capital: str = ""
    industry: str = ""
    address: str = ""
    risk_summary: str = ""


class StakeholderModel(BaseModel):
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None
    name: str
    role: str = ""
    relation: str = ""
    company: str = ""
    phone: str = ""
    wechat_id: str = ""
    influence: str = "medium"
    notes: str = ""


class TagModel(BaseModel):
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None
    tag: str
    source: str = "manual"


class RiskModel(BaseModel):
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None
    risk_type: str
    level: str = "medium"
    content: str = ""
    source: str = "manual"


class RiskStatusModel(BaseModel):
    status: str


class JourneyModel(BaseModel):
    session_id: str = ""
    customer_id: int = None
    lead_id: int = None
    channel: str
    action: str
    detail: str = ""


@router.get("/portrait")
async def get_portrait(
    session_id: str = Query(""),
    customer_id: int = Query(0),
    lead_id: int = Query(0),
):
    return portrait_manager.portrait(
        session_id=session_id,
        customer_id=customer_id or None,
        lead_id=lead_id or None,
    )


@router.post("/portrait/business-profile", dependencies=[Depends(require_admin)])
async def upsert_business_profile(req: BusinessProfileModel):
    data = req.model_dump()
    return {"profile": portrait_manager.upsert_business_profile(
        session_id=data.pop("session_id", ""),
        customer_id=data.pop("customer_id", None),
        lead_id=data.pop("lead_id", None),
        **data,
    )}


@router.post("/portrait/stakeholders", dependencies=[Depends(require_admin)])
async def add_stakeholder(req: StakeholderModel):
    return {"stakeholder": portrait_manager.add_stakeholder(**req.model_dump())}


@router.post("/portrait/tags", dependencies=[Depends(require_admin)])
async def add_tag(req: TagModel):
    return {"tag": portrait_manager.add_tag(**req.model_dump())}


@router.post("/portrait/risks", dependencies=[Depends(require_admin)])
async def add_risk(req: RiskModel):
    return {"risk": portrait_manager.add_risk(**req.model_dump())}


@router.post("/portrait/risks/{risk_id}/status", dependencies=[Depends(require_admin)])
async def update_risk_status(risk_id: int, req: RiskStatusModel):
    return {"risk": portrait_manager.update_risk_status(risk_id, req.status)}


@router.post("/portrait/journey", dependencies=[Depends(require_admin)])
async def add_journey(req: JourneyModel):
    return {"journey": portrait_manager.add_journey(**req.model_dump())}


@router.post("/portrait/scan-risks", dependencies=[Depends(require_admin)])
async def scan_risks():
    return portrait_manager.auto_scan_risks()
