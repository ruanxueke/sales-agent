"""优化复盘接口：A/B 实验、周复盘、指标"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.optimization import optimization_manager
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["optimization"], dependencies=[Depends(require_api_key)])


class ExperimentModel(BaseModel):
    name: str
    kind: str = "script"
    control: str = ""
    variant: str = ""
    note: str = ""


class UpdateModel(BaseModel):
    fields: dict = {}


class RunModel(BaseModel):
    session_id: str
    variant: str = "control"
    result: str = ""


class ReviewModel(BaseModel):
    content: str
    week_start: str = ""


@router.get("/optimization/experiments")
async def list_experiments(status: str = Query(""), limit: int = Query(200, le=1000)):
    return {"experiments": optimization_manager.list_experiments(status=status, limit=limit)}


@router.post("/optimization/experiments", dependencies=[Depends(require_admin)])
async def create_experiment(req: ExperimentModel):
    return {"experiment": optimization_manager.create_experiment(req.name, req.kind, req.control, req.variant, req.note)}


@router.patch("/optimization/experiments/{item_id}", dependencies=[Depends(require_admin)])
async def update_experiment(item_id: int, req: UpdateModel):
    return {"experiment": optimization_manager.update_experiment(item_id, **req.fields)}

@router.delete("/optimization/experiments/{item_id}", dependencies=[Depends(require_admin)])
async def delete_experiment(item_id: int):
    return {"deleted": optimization_manager.delete_experiment(item_id)}


@router.get("/optimization/runs")
async def list_runs(experiment_id: int = Query(0), limit: int = Query(200, le=1000)):
    return {"runs": optimization_manager.list_runs(experiment_id=experiment_id, limit=limit)}


@router.post("/optimization/runs", dependencies=[Depends(require_admin)])
async def record_run(experiment_id: int, req: RunModel):
    return {"run": optimization_manager.record_run(experiment_id, req.session_id, req.variant, req.result)}


@router.get("/optimization/reviews")
async def list_reviews(limit: int = Query(50, le=500)):
    return {"reviews": optimization_manager.list_reviews(limit=limit)}


@router.post("/optimization/reviews", dependencies=[Depends(require_admin)])
async def create_review(req: ReviewModel):
    return {"review": optimization_manager.create_review(req.content, req.week_start)}

@router.delete("/optimization/reviews/{item_id}", dependencies=[Depends(require_admin)])
async def delete_review(item_id: int):
    return {"deleted": optimization_manager.delete_review(item_id)}


@router.get("/optimization/metrics")
async def optimization_metrics(days: int = Query(7, ge=1, le=90)):
    return optimization_manager.metric_summary(days=days)


@router.get("/optimization/stats")
async def optimization_stats():
    return optimization_manager.stats()
