"""Celery 任务定义 — 异步处理用户消息"""
from __future__ import annotations
import logging
from typing import Optional

from celery import Celery
from config.settings import settings

logger = logging.getLogger(__name__)

# 创建 Celery 应用
celery_app = Celery(
    "sales_agent",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,           # 任务完成后才确认，防止丢失
    worker_prefetch_multiplier=1,  # 一个 worker 一次只拿一个任务
    task_default_queue=settings.CELERY_TASK_DEFAULT_QUEUE,
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
    task_soft_time_limit=120,      # 任务软超时 120 秒
    task_time_limit=180,           # 任务硬超时 180 秒
    result_expires=3600,           # 结果保留 1 小时
)


@celery_app.task(
    bind=True,
    name="process_message",
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def process_message_task(self, session_id: str, message: str) -> dict:
    """处理用户消息的 Celery 任务

    这个函数会被 Celery Worker 调用，在 Worker 进程中执行。
    """
    logger.info(f"[任务] 处理 {session_id[:16]}... 的消息: {message[:50]}...")

    try:
        # 延迟导入，避免 Worker 启动时加载全部依赖
        from core.agent import sales_agent

        reply = sales_agent.chat(message, session_id=session_id)

        logger.info(f"[任务完成] {session_id[:16]}... 回复长度: {len(reply)}")
        return {"status": "success", "session_id": session_id, "reply": reply}

    except Exception as exc:
        logger.error(f"[任务失败] {session_id[:16]}...: {exc}")
        try:
            self.retry(exc=exc)
        except Exception as final_exc:
            logger.error(f"[任务最终失败] {session_id[:16]}...: {final_exc}")
            return {
                "status": "error",
                "session_id": session_id,
                "error": str(final_exc),
            }


@celery_app.task(name="health_check")
def health_check() -> dict:
    """健康检查任务"""
    return {"status": "ok", "worker": "alive"}
