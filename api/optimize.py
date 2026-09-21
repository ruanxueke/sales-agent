"""对话质量自优化接口"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.self_optimize import (
    auto_scorer,
    prompt_version_mgr,
    ab_test_mgr,
    optimization_engine,
)
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["optimize"], dependencies=[Depends(require_api_key)])


class GenericModel(BaseModel):
    fields: dict = {}


# ===== 评分 =====
@router.get("/optimize/scores")
async def list_scores(
    session_id: str = Query(""),
    product: str = Query(""),
    limit: int = Query(50),
):
    from core.db import init_db, session_scope
    from core.models import ConversationScore
    from sqlalchemy import select
    init_db()
    with session_scope() as session:
        query = select(ConversationScore).order_by(ConversationScore.id.desc())
        if session_id:
            query = query.where(ConversationScore.session_id == session_id)
        if product:
            query = query.where(ConversationScore.product == product)
        rows = session.execute(query.limit(limit)).scalars().all()
        return {"scores": [
            {c.name: getattr(r, c.name) for c in r.__table__.columns}
            for r in rows
        ]}


@router.get("/optimize/scores/stats")
async def score_stats(days: int = Query(7)):
    from core.db import init_db, session_scope
    from core.models import ConversationScore
    from sqlalchemy import select, func
    from datetime import datetime, timedelta
    init_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with session_scope() as session:
        rows = session.execute(
            select(ConversationScore).where(ConversationScore.created_at >= cutoff)
        ).scalars().all()
        if not rows:
            return {"total": 0, "avg_score": 0, "by_product": {}, "by_dimension": {}}
        
        avg = sum(r.total_score for r in rows) / len(rows)
        by_product = {}
        for r in rows:
            p = r.product or "unknown"
            if p not in by_product:
                by_product[p] = {"count": 0, "avg": 0, "scores": []}
            by_product[p]["count"] += 1
            by_product[p]["scores"].append(r.total_score)
        for p in by_product:
            scores = by_product[p]["scores"]
            by_product[p]["avg"] = round(sum(scores) / len(scores), 1)
            del by_product[p]["scores"]
        
        by_dim = {
            "conversion": round(sum(r.conversion_score for r in rows) / len(rows), 1),
            "compliance": round(sum(r.compliance_score for r in rows) / len(rows), 1),
            "satisfaction": round(sum(r.satisfaction_score for r in rows) / len(rows), 1),
            "response": round(sum(r.response_score for r in rows) / len(rows), 1),
        }
        
        return {"total": len(rows), "avg_score": round(avg, 1), "by_product": by_product, "by_dimension": by_dim}


# ===== Prompt 版本管理 =====
@router.get("/optimize/prompts")
async def list_prompt_versions():
    return {"versions": prompt_version_mgr.list_versions()}


@router.post("/optimize/prompts", dependencies=[Depends(require_admin)])
async def save_prompt_version(req: GenericModel):
    content = req.fields.get("content", "")
    desc = req.fields.get("description", "")
    return {"version": prompt_version_mgr.save_version(content, desc)}


@router.post("/optimize/prompts/{version_id}/activate", dependencies=[Depends(require_admin)])
async def activate_prompt_version(version_id: int):
    result = prompt_version_mgr.activate(version_id)
    if not result:
        return {"error": "Version not found"}
    return {"activated": result}


@router.get("/optimize/prompts/active")
async def get_active_prompt():
    return {"active": prompt_version_mgr.get_active()}


# ===== A/B 测试 =====
@router.get("/optimize/experiments")
async def list_experiments(status: str = Query("")):
    from core.db import init_db, session_scope
    from core.models import AbExperiment
    from sqlalchemy import select
    init_db()
    with session_scope() as session:
        query = select(AbExperiment).order_by(AbExperiment.id.desc())
        if status:
            query = query.where(AbExperiment.status == status)
        rows = session.execute(query.limit(50)).scalars().all()
        return {"experiments": [
            {c.name: getattr(r, c.name) for c in r.__table__.columns}
            for r in rows
        ]}


@router.post("/optimize/experiments", dependencies=[Depends(require_admin)])
async def create_experiment(req: GenericModel):
    return {"experiment": ab_test_mgr.create_experiment(
        name=req.fields.get("name", ""),
        control_prompt=req.fields.get("control", ""),
        variant_prompt=req.fields.get("variant", ""),
        kind=req.fields.get("kind", "prompt"),
        description=req.fields.get("description", ""),
    )}


@router.post("/optimize/experiments/{exp_id}/start", dependencies=[Depends(require_admin)])
async def start_experiment(exp_id: int):
    result = ab_test_mgr.start_experiment(exp_id)
    if not result:
        return {"error": "Experiment not found"}
    return {"started": result}


@router.get("/optimize/experiments/{exp_id}/results")
async def get_experiment_results(exp_id: int):
    return ab_test_mgr.get_results(exp_id)


# ===== 优化建议 =====
@router.get("/optimize/suggestions")
async def list_suggestions(status: str = Query("")):
    return {"suggestions": optimization_engine.list_suggestions(status=status)}


@router.post("/optimize/suggestions/generate", dependencies=[Depends(require_admin)])
async def generate_suggestions(days: int = Query(7)):
    suggestions = optimization_engine.generate_suggestions(days=days)
    return {"generated": len(suggestions), "suggestions": suggestions}



@router.post("/optimize/suggestions/{sug_id}/approve", dependencies=[Depends(require_admin)])
async def approve_suggestion(sug_id: int):
    result = optimization_engine.approve_suggestion(sug_id)
    if not result:
        return {"error": "Suggestion not found"}
    return {"approved": result}


@router.post("/optimize/suggestions/{sug_id}/reject", dependencies=[Depends(require_admin)])
async def reject_suggestion(sug_id: int):
    result = optimization_engine.reject_suggestion(sug_id)
    if not result:
        return {"error": "Suggestion not found"}
    return {"rejected": result}
