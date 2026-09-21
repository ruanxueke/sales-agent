"""并发改造自检 API"""
from __future__ import annotations
from fastapi import APIRouter, Depends

from core.concurrency_check import run_concurrency_check
from core.security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["concurrency-check"], dependencies=[Depends(require_api_key)])


@router.get("/system/concurrency-check")
async def concurrency_check():
    return run_concurrency_check()
