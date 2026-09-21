"""定时任务调度器：支持 Celery Beat（生产）和 Threading（降级）

模式选择：
- 有 Celery + Redis → Celery Beat 模式（独立进程调度）
- 无 Celery → Threading 模式（当前方式，进程内调度）
"""
from __future__ import annotations
import logging
import threading
import time
from datetime import date

from config.settings import settings

logger = logging.getLogger(__name__)


class BackgroundScheduler:
    """线程模式调度器（降级方案）"""

    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self._stop_event = threading.Event()
        self._thread = None
        self._last_quality_day = ""
        self._last_backup_day = ""
        self._last_rebuild_day = ""
        self._last_audit_purge_day = ""

    def start(self) -> None:
        if not settings.ENABLE_SCHEDULER:
            logger.info("定时任务已禁用（ENABLE_SCHEDULER=false）")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="sales-scheduler", daemon=True)
        self._thread.start()
        logger.info("定时任务已启动（线程模式），间隔 %s 秒", self.interval)

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._run_jobs()
            except Exception as e:
                logger.error(f"定时任务执行异常: {e}")
            self._stop_event.wait(self.interval)

    def _run_jobs(self) -> None:
        try:
            from core.alerting import alert_manager
            alert_manager.run_checks()
        except Exception as e:
            logger.error(f"定时监控告警失败: {e}")

        try:
            from core.lead import lead_manager
            recycled = lead_manager.recycle()
            if recycled:
                logger.info("定时公海回收 %s 条", recycled)
        except Exception as e:
            logger.error(f"定时公海回收失败: {e}")

        try:
            from core.followup import followup_engine
            sent = followup_engine.dispatch_due()
            if sent:
                logger.info("定时自动跟进发送 %s 条", sent)
        except Exception as e:
            logger.error(f"定时自动跟进失败: {e}")

        try:
            from core.opportunity import opportunity_manager
            result = opportunity_manager.refresh_risk()
            if result.get("updated"):
                logger.info("商机停滞预警更新 %s 条", result["updated"])
        except Exception as e:
            logger.error(f"商机停滞预警失败: {e}")

        try:
            from core.finance import finance_manager
            result = finance_manager.refresh_overdue()
            if result.get("plans") or result.get("receivables"):
                logger.info("回款逾期更新：计划 %s，应收 %s", result["plans"], result["receivables"])
        except Exception as e:
            logger.error(f"回款逾期检查失败: {e}")

        try:
            from core.sop import sop_manager
            result = sop_manager.refresh_overdue()
            if result.get("overdue"):
                logger.info("SOP逾期步骤 %s 条", result["overdue"])
        except Exception as e:
            logger.error(f"SOP逾期检查失败: {e}")

        try:
            from core.ticket import ticket_manager
            result = ticket_manager.refresh_overdue()
            if result.get("overdue"):
                logger.info("工单SLA逾期 %s 条", result["overdue"])
        except Exception as e:
            logger.error(f"工单SLA检查失败: {e}")

        try:
            from core.cpq import cpq_manager
            result = cpq_manager.refresh_contract_risk()
            if result.get("updated"):
                logger.info("合同风险更新 %s 条", result["updated"])
        except Exception as e:
            logger.error(f"合同风险检查失败: {e}")

        try:
            from core.nurture import nurture_manager
            result = nurture_manager.dispatch_due()
            if result.get("sent"):
                logger.info("培育触达完成 %s 条", result["sent"])
        except Exception as e:
            logger.error(f"培育触达失败: {e}")

        try:
            from core.marketing import marketing_manager
            dispatched = marketing_manager.dispatch_due_repurchases()
            if dispatched:
                logger.info("复购计划派发 %s 条", dispatched)
        except Exception as e:
            logger.error(f"复购计划派发失败: {e}")

        today = date.today().isoformat()
        if today != self._last_quality_day:
            try:
                from core.quality import quality_checker
                count = quality_checker.scan_active_customers()
                self._last_quality_day = today
                logger.info("定时质检完成 %s 个客户", count)
            except Exception as e:
                logger.error(f"定时质检失败: {e}")

        try:
            from core.portrait import portrait_manager
            result = portrait_manager.auto_scan_risks()
            if result.get("created"):
                logger.info("画像自动风险扫描新增 %s 条", result["created"])
        except Exception as e:
            logger.error(f"画像风险扫描失败: {e}")

        if today != self._last_backup_day:
            try:
                from core.backup import backup_data
                result = backup_data()
                self._last_backup_day = today
                logger.info("每日数据备份完成: %s", result["dir"])
                try:
                    from core.backup import archive_backup
                    archive_result = archive_backup()
                    logger.info("备份归档完成: %s", archive_result.get("uploaded", 0))
                except Exception as archive_err:
                    logger.error(f"备份归档失败: {archive_err}")
            except Exception as e:
                logger.error(f"每日数据备份失败: {e}")

        if today != self._last_rebuild_day:
            try:
                from knowledge.knowledge_manager import KnowledgeManager
                KnowledgeManager().import_from_directory()
                self._last_rebuild_day = today
                logger.info("每日知识库重建完成")
            except Exception as e:
                logger.error(f"每日知识库重建失败: {e}")

        if today != self._last_audit_purge_day:
            try:
                from core.audit import purge_audit
                result = purge_audit()
                self._last_audit_purge_day = today
                logger.info("审计日志留存清理: 数据库 %s 条, 文件 %s 个", result["removed_db"], result["removed_files"])
            except Exception as e:
                logger.error(f"审计日志留存清理失败: {e}")


# ============================================================
# 统一调度入口
# ============================================================

scheduler = BackgroundScheduler(interval_seconds=settings.SCHEDULER_INTERVAL_SECONDS)


def start_scheduler():
    """启动调度器（自动选择模式）"""
    from core.tasks import get_celery_app
    app = get_celery_app()
    if app:
        _setup_celery_beat(app)
        logger.info("定时任务已注册到 Celery Beat")
    else:
        scheduler.start()


def _setup_celery_beat(app):
    """配置 Celery Beat 定时任务"""
    from celery.schedules import crontab

    app.conf.beat_schedule = {
        "recycle-leads": {
            "task": "tasks.recycle_leads",
            "schedule": crontab(minute="*/5"),
        },
        "auto-followup": {
            "task": "tasks.auto_followup",
            "schedule": crontab(minute="*/5"),
        },
        "quality-check": {
            "task": "tasks.quality_check",
            "schedule": crontab(hour=2, minute=0),
        },
        "generate-suggestions": {
            "task": "tasks.generate_suggestions",
            "schedule": crontab(hour=3, minute=0, day_of_week="monday"),
            "args": (7,),
        },
        "backup-database": {
            "task": "tasks.backup_database",
            "schedule": crontab(hour=4, minute=0),
        },
        "privacy-retention": {
            "task": "tasks.purge_expired_privacy",
            "schedule": crontab(hour=4, minute=20),
        },
    }
