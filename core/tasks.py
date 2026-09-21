"""Celery 定时任务与异步任务：统一调度，替代旧 scheduler"""
from __future__ import annotations
import logging
import os
import sys

# 确保项目根目录在 sys.path（Worker/Beat 容器内都能找到 core/config）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

from celery import Celery

broker = os.environ.get("CELERY_BROKER_URL", "") or os.environ.get("REDIS_URL", "")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "") or os.environ.get("REDIS_URL", "")
if not broker:
    logger.warning(
        "未设置 CELERY_BROKER_URL / REDIS_URL，回退到 redis://localhost:6379/1；"
        "多容器部署下会导致「生产者与消费者不在同一个 Redis 库」而任务永不消费，请检查环境变量"
    )
if not result_backend:
    logger.warning("未设置 CELERY_RESULT_BACKEND，任务执行结果将不可查询")

celery = Celery("sales_agent", broker=broker or "redis://localhost:6379/1", backend=result_backend or None)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=120,
    task_time_limit=180,
    task_default_queue="sales_agent",
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "alert-checks-every-minute": {"task": "tasks.alert_checks", "schedule": 60.0},
        "lead-recycle-every-5min": {"task": "tasks.recycle_leads", "schedule": 300.0},
        "auto-followup-every-minute": {"task": "tasks.auto_followup", "schedule": 60.0},
        "opportunity-risk-every-10min": {"task": "tasks.refresh_opportunity_risk", "schedule": 600.0},
        "finance-overdue-every-10min": {"task": "tasks.refresh_finance_overdue", "schedule": 600.0},
        "sop-overdue-every-10min": {"task": "tasks.refresh_sop_overdue", "schedule": 600.0},
        "ticket-sla-every-10min": {"task": "tasks.refresh_ticket_sla", "schedule": 600.0},
        "cpq-risk-every-10min": {"task": "tasks.refresh_cpq_risk", "schedule": 600.0},
        "nurture-every-5min": {"task": "tasks.dispatch_nurture", "schedule": 300.0},
        "repurchase-every-5min": {"task": "tasks.dispatch_repurchases", "schedule": 300.0},
        "portrait-risk-every-30min": {"task": "tasks.scan_portrait_risks", "schedule": 1800.0},
        "quality-scan-daily": {"task": "tasks.quality_check", "schedule": 86400.0},
        "backup-daily": {"task": "tasks.backup_database", "schedule": 86400.0},
        "knowledge-rebuild-daily": {"task": "tasks.rebuild_knowledge", "schedule": 86400.0},
        "audit-purge-daily": {"task": "tasks.purge_audit", "schedule": 86400.0},
        "privacy-retention-daily": {"task": "tasks.purge_expired_privacy", "schedule": 86400.0},
    },
)


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.error("Task %s failed: %s", getattr(fn, "__name__", "?"), e)
            return None
    return wrapper


# ===== 任务实现 =====

@_safe
def alert_checks():
    from core.alerting import alert_manager
    alert_manager.run_checks()


@_safe
def recycle_leads():
    from core.lead import lead_manager
    return lead_manager.recycle()


@_safe
def auto_followup():
    from core.followup import followup_engine
    return followup_engine.dispatch_due()


@_safe
def refresh_opportunity_risk():
    from core.opportunity import opportunity_manager
    return opportunity_manager.refresh_risk()


@_safe
def refresh_finance_overdue():
    from core.finance import finance_manager
    return finance_manager.refresh_overdue()


@_safe
def refresh_sop_overdue():
    from core.sop import sop_manager
    return sop_manager.refresh_overdue()


@_safe
def refresh_ticket_sla():
    from core.ticket import ticket_manager
    return ticket_manager.refresh_overdue()


@_safe
def refresh_cpq_risk():
    from core.cpq import cpq_manager
    return cpq_manager.refresh_contract_risk()


@_safe
def dispatch_nurture():
    from core.nurture import nurture_manager
    return nurture_manager.dispatch_due()


@_safe
def dispatch_repurchases():
    from core.marketing import marketing_manager
    return marketing_manager.dispatch_due_repurchases()


@_safe
def scan_portrait_risks():
    from core.portrait import portrait_manager
    return portrait_manager.auto_scan_risks()


@_safe
def quality_check():
    from core.quality import quality_checker
    return quality_checker.scan_active_customers()


@_safe
def backup_database():
    from core.backup import backup_data, archive_backup
    result = backup_data()
    try:
        archive_backup()
    except Exception as e:
        logger.error("备份归档失败: %s", e)
    return result


@_safe
def rebuild_knowledge():
    from knowledge.knowledge_manager import KnowledgeManager
    return KnowledgeManager().import_from_directory()


@_safe
def purge_audit():
    from core.audit import purge_audit as purge
    return purge()


@_safe
def purge_expired_privacy():
    from core.privacy import purge_expired_chat
    return purge_expired_chat()


@_safe
def score_conversation(session_id="", customer_id=None, product=""):
    from core.self_optimize import auto_scorer
    return auto_scorer.score_conversation(session_id=session_id, customer_id=customer_id, product=product)


@_safe
def generate_suggestions(days=7):
    from core.self_optimize import optimization_engine
    return optimization_engine.generate_suggestions(days=days)
@celery.task(
    name="tasks.send_channel_reply",
    bind=True,
    acks_late=True,
    max_retries=5,
    default_retry_delay=3,
)
def send_channel_reply_task(self, payload: dict):
    """渠道统一回复任务：生成回复并发送；可重试错误按指数退避重试。"""
    from core.reply_dispatcher import run_reply_task
    result = run_reply_task(payload)
    if not result.get("ok") and result.get("retryable"):
        countdown = min(30, 3 * (int(getattr(self.request, "retries", 0) or 0) + 1))
        raise self.retry(countdown=countdown)
    return result


# ===== 注册 Celery 任务 =====

_TASK_FUNCS = {
    "alert_checks": alert_checks,
    "recycle_leads": recycle_leads,
    "auto_followup": auto_followup,
    "refresh_opportunity_risk": refresh_opportunity_risk,
    "refresh_finance_overdue": refresh_finance_overdue,
    "refresh_sop_overdue": refresh_sop_overdue,
    "refresh_ticket_sla": refresh_ticket_sla,
    "refresh_cpq_risk": refresh_cpq_risk,
    "dispatch_nurture": dispatch_nurture,
    "dispatch_repurchases": dispatch_repurchases,
    "scan_portrait_risks": scan_portrait_risks,
    "quality_check": quality_check,
    "backup_database": backup_database,
    "rebuild_knowledge": rebuild_knowledge,
    "purge_audit": purge_audit,
    "purge_expired_privacy": purge_expired_privacy,
    "score_conversation": score_conversation,
    "generate_suggestions": generate_suggestions,
}

for _name, _func in _TASK_FUNCS.items():
    celery.task(name=f"tasks.{_name}")(_func)


def send_task(task_name, args=None, kwargs=None):
    """发送异步任务；Celery 不可用时同步执行兜底"""
    try:
        celery.send_task(f"tasks.{task_name}", args=args or [], kwargs=kwargs or {})
        return True
    except Exception as e:
        logger.warning("Celery send failed, running sync: %s", e)
        func = _TASK_FUNCS.get(task_name)
        if func:
            try:
                func(**(kwargs or {}))
            except Exception as ex:
                logger.error("Sync task %s failed: %s", task_name, ex)
        return False
