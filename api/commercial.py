"""商用化核心闭环 API：统一会话、智能路由、CDP/RFM、营销旅程、内容安全"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from core.commercial import commercial
from core.security import current_tenant, require_admin, require_api_key
import logging
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1", tags=["commercial"], dependencies=[Depends(require_api_key)])


class IngestModel(BaseModel):
    channel: str = "webchat"
    external_id: str
    content: str
    direction: str = "in"
    session_key: str = ""
    customer_id: int = None
    nickname: str = ""
    source_page: str = ""
    msg_type: str = "text"


class RouteRuleCreate(BaseModel):
    name: str = ""
    condition: dict = {}
    target: str = "robot"
    priority: int = 0
    enabled: bool = True


class RouteModel(BaseModel):
    session_id: int


class TagModel(BaseModel):
    tag: str
    customer_id: int = None
    lead_id: int = None
    session_id: str = ""
    source: str = "manual"


class JourneyCreate(BaseModel):
    name: str
    trigger: str = "manual"
    nodes: list[dict] = []
    enabled: bool = True
    daily_limit: int = 100


class JourneyRun(BaseModel):
    context: dict = {}


class TriggerModel(BaseModel):
    event: str
    context: dict = {}


class ModerationRuleCreate(BaseModel):
    name: str = ""
    keywords: str = ""
    action: str = "block"
    enabled: bool = True


class CheckModel(BaseModel):
    text: str


class AssignModel(BaseModel):
    agent: str


def _tenant(request: Request):
    return current_tenant(request)


# ===== 统一会话通道 =====

@router.post("/commercial/channel/ingest")
async def channel_ingest(req: IngestModel, request: Request = None):
    result = commercial.ingest_message(
        current_tenant(request),
        req.channel,
        req.external_id,
        req.content,
        req.direction,
        req.session_key,
        req.customer_id,
        req.nickname,
        req.source_page,
        req.msg_type,
    )
    if result.get("ok") and result.get("session"):
        session_id = result["session"].get("id")
        try:
            route = commercial.route_session(current_tenant(request), session_id)
            result["route"] = route
        except Exception as e:
            logger.warning("会话租户路由失败，本次不归属任何租户: %s", e)
    return result


@router.get("/commercial/channel/sessions")
async def channel_sessions(status: str = Query(""), limit: int = Query(100, le=500), request: Request = None):
    return {"items": commercial.list_sessions(current_tenant(request), status, limit)}


@router.get("/commercial/channel/sessions/{session_id}/messages")
async def channel_messages(session_id: int, limit: int = Query(100, le=500), request: Request = None):
    return {"items": commercial.session_messages(current_tenant(request), session_id, limit)}


@router.post("/commercial/channel/sessions/{session_id}/close")
async def channel_close(session_id: int, request: Request = None):
    return {"ok": commercial.close_session(current_tenant(request), session_id)}


@router.post("/commercial/channel/sessions/{session_id}/assign")
async def channel_assign(session_id: int, req: AssignModel, request: Request = None):
    return {"ok": commercial.assign_session(current_tenant(request), session_id, req.agent)}


# ===== 智能路由 =====

@router.get("/commercial/router/rules")
async def router_rules(request: Request = None):
    return {"items": commercial.list_rules(current_tenant(request))}


@router.post("/commercial/router/rules", dependencies=[Depends(require_admin)])
async def router_rule_create(req: RouteRuleCreate, request: Request = None):
    return {"rule": commercial.create_rule(current_tenant(request), req.name, req.condition, req.target, req.priority, req.enabled)}


@router.delete("/commercial/router/rules/{rule_id}", dependencies=[Depends(require_admin)])
async def router_rule_delete(rule_id: int, request: Request = None):
    return {"ok": commercial.delete_rule(rule_id, current_tenant(request))}


@router.post("/commercial/router/route")
async def router_route(req: RouteModel, request: Request = None):
    return commercial.route_session(current_tenant(request), req.session_id)


# ===== CDP / RFM =====

@router.get("/commercial/cdp/tags")
async def cdp_tags(customer_id: int = Query(0), lead_id: int = Query(0), request: Request = None):
    return {"items": commercial.list_tags(current_tenant(request), customer_id or None, lead_id or None)}


@router.post("/commercial/cdp/tags")
async def cdp_tag_add(req: TagModel, request: Request = None):
    return {"tag": commercial.add_tag(current_tenant(request), req.tag, req.customer_id, req.lead_id, req.session_id, req.source)}


@router.get("/commercial/cdp/rfm")
async def cdp_rfm(request: Request = None):
    return commercial.rfm(current_tenant(request))


@router.get("/commercial/cdp/segment")
async def cdp_segment(tag: str = Query(""), request: Request = None):
    return {"items": commercial.segment_by_tag(current_tenant(request), tag)}


# ===== 营销自动化旅程 =====

@router.get("/commercial/marketing/journeys")
async def marketing_journeys(request: Request = None):
    return {"items": commercial.list_journeys(current_tenant(request))}


@router.post("/commercial/marketing/journeys", dependencies=[Depends(require_admin)])
async def marketing_journey_create(req: JourneyCreate, request: Request = None):
    return {"journey": commercial.create_journey(current_tenant(request), req.name, req.trigger, req.nodes, req.enabled, req.daily_limit)}


@router.delete("/commercial/marketing/journeys/{journey_id}", dependencies=[Depends(require_admin)])
async def marketing_journey_delete(journey_id: int, request: Request = None):
    return {"ok": commercial.delete_journey(journey_id, current_tenant(request))}


@router.post("/commercial/marketing/journeys/{journey_id}/run")
async def marketing_journey_run(journey_id: int, req: JourneyRun = None, request: Request = None):
    return commercial.run_journey(journey_id, (req or JourneyRun()).context, current_tenant(request))


@router.post("/commercial/marketing/trigger")
async def marketing_trigger(req: TriggerModel, request: Request = None):
    results = commercial.trigger_journey(req.event, req.context, current_tenant(request))
    return {"ok": True, "matched": len(results), "results": results}


# ===== 内容安全 =====

@router.get("/commercial/content-safety/rules")
async def safety_rules(request: Request = None):
    return {"items": commercial.list_moderation_rules(current_tenant(request))}


@router.post("/commercial/content-safety/rules", dependencies=[Depends(require_admin)])
async def safety_rule_create(req: ModerationRuleCreate, request: Request = None):
    return {"rule": commercial.create_moderation_rule(current_tenant(request), req.name, req.keywords, req.action, req.enabled)}


@router.delete("/commercial/content-safety/rules/{rule_id}", dependencies=[Depends(require_admin)])
async def safety_rule_delete(rule_id: int, request: Request = None):
    return {"ok": commercial.delete_moderation_rule(rule_id, current_tenant(request))}


@router.post("/commercial/content-safety/check")
async def safety_check(req: CheckModel, request: Request = None):
    return commercial.check_text(req.text, current_tenant(request))
