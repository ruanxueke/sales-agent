"""会话标注回灌接口"""
from __future__ import annotations
import logging
import re
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from core.feedback import feedback_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["feedback"], dependencies=[Depends(require_api_key)])


class FeedbackCreate(BaseModel):
    session_id: str = ""
    message: str = ""
    reply: str = ""
    rating: str = "bad"
    issue_type: str = ""
    standard_reply: str = ""
    note: str = ""
    customer_id: int = None


class FeedbackUpdate(BaseModel):
    status: str = ""
    standard_reply: str = ""


@router.get("/feedback")
async def list_feedback(status: str = Query(""), limit: int = Query(200, le=1000)):
    return {"items": feedback_manager.list(status=status, limit=limit)}


@router.get("/feedback/summary")
async def feedback_summary():
    return feedback_manager.summary()


class AutoScoreModel(BaseModel):
    session_id: str
    limit: int = 10


@router.post("/feedback/auto-score", dependencies=[Depends(require_admin)])
async def auto_score(req: AutoScoreModel):
    from core.llm import create_llm
    from langchain_core.prompts import PromptTemplate
    from core.sales_crm import crm
    customer = crm.get_by_session(req.session_id)
    if not customer:
        return {"ok": False, "error": "客户不存在", "created": 0, "items": []}
    logs = crm.get_chat_log(customer["id"], limit=req.limit * 2)
    pairs = []
    for i, row in enumerate(logs):
        if row.get("role") in ("客户", "customer") and i + 1 < len(logs):
            nxt = logs[i + 1]
            if nxt.get("role") in ("客服", "agent", "assistant"):
                pairs.append({"message": row.get("content", ""), "reply": nxt.get("content", "")})
    if not pairs:
        return {"ok": False, "error": "没有可评分的对话", "created": 0, "items": []}
    prompt = PromptTemplate.from_template(
        "你是销售质检专家。给下面的客服回复打分(0-100)，并指出问题类型(简短中文，如：太啰嗦/没推进/语气差/答非所问)。\n客户:{message}\n客服:{reply}\n只输出JSON:{{\"score\":0,\"issue\":\"\"}}"
    )
    llm = create_llm()
    chain = prompt | llm
    created = 0
    items = []
    for p in pairs[:req.limit]:
        try:
            out = chain.invoke({"message": p["message"], "reply": p["reply"]})
            text = out.content if hasattr(out, "content") else str(out)
            m = re.search(r'"score"\s*:\s*(\d+)', text)
            score = int(m.group(1)) if m else 0
            m2 = re.search(r'"issue"\s*:\s*"([^"]+)"', text)
            issue = m2.group(1) if m2 else "自动评分"
            if score < 70:
                item = feedback_manager.add(
                    session_id=req.session_id, message=p["message"], reply=p["reply"],
                    rating="bad", issue_type=issue or "自动评分", note=f"AI评分{score}",
                )
                items.append(item)
                created += 1
        except Exception as e:
            logger.warning(f"自动评分失败: {e}")
    return {"ok": True, "created": created, "items": items}


@router.post("/feedback", dependencies=[Depends(require_admin)])
async def create_feedback(req: FeedbackCreate):
    return {"item": feedback_manager.add(**req.model_dump())}


@router.patch("/feedback/{item_id}", dependencies=[Depends(require_admin)])
async def update_feedback(item_id: int, req: FeedbackUpdate):
    return {"item": feedback_manager.update(item_id, req.status, req.standard_reply)}


@router.post("/feedback/{item_id}/backfill", dependencies=[Depends(require_admin)])
async def backfill_feedback(item_id: int):
    result = feedback_manager.backfill_to_ammo(item_id)
    if not result:
        return {"ok": False, "error": "未找到可回灌的标注（需要先填写标准话术）"}
    return {"ok": True, **result}
