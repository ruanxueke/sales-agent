"""销售线索通知：客户达到 L3 后生成通知，接收人可在配置中指定（当前为占位）"""
from __future__ import annotations
import logging
from datetime import datetime

import requests

from config.settings import settings
from core.sales_crm import crm

logger = logging.getLogger(__name__)


def format_notification(customer: dict, chat_log: list[dict], lead_id: str = "") -> str:
    lines = [
        "【新线索】客户达到 L3 意向，请及时跟进",
        f"线索ID：{lead_id or '未生成'}",
        f"客户ID：{customer.get('session_id') or '未提供'}",
        f"昵称：{customer.get('nickname') or '未提供'}",
        f"身份：{customer.get('identity') or '未提供'}",
        f"基础：{customer.get('level') or '未提供'}",
        f"目标：{customer.get('goal') or '未提供'}",
        f"预算：{customer.get('budget') or '未提供'}",
        f"兴趣课程：{customer.get('interest') or '未提供'}",
        f"意向等级：{customer.get('intent_level') or '未提供'}",
        f"销售阶段：{customer.get('stage') or '未提供'}",
        "",
        "--- 最近聊天记录 ---",
    ]
    for item in chat_log[-20:]:
        lines.append(f"{item['role']}: {item['content']}")
    return "\n".join(lines)


def notify_sales(customer: dict, chat_log: list[dict]) -> int:
    """生成销售线索通知，落库并写入通知日志（接收人未配置时为占位）"""
    lead_id = ""
    try:
        from core.lead import lead_manager
        lead = lead_manager.upsert_from_customer(
            customer,
            source=customer.get("source") or "wechat",
        )
        if lead:
            lead_id = str(lead.get("id") or "")
            try:
                from core.followup import followup_engine
                followup_engine.plan_for_lead(lead, customer=customer)
            except Exception as e:
                logger.error(f"自动跟进计划创建失败: {e}")
    except Exception as e:
        logger.error(f"线索建档失败: {e}")

    content = format_notification(customer, chat_log, lead_id=lead_id)
    target = settings.LEAD_DEFAULT_OWNER or settings.SALES_NOTIFY_TARGET or "未配置（占位）"
    notification_id = crm.create_notification(customer["id"], target, content)

    log_dir = settings.DATA_DIR / "notifications"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.txt"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(
            f"\n===== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 通知#{notification_id} =====\n"
            f"{content}\n"
        )

    logger.info("已生成销售线索通知 #%s，接收人: %s", notification_id, target)

    if target and target != "未配置（占位）":
        try:
            from core.bot_notify import send_bot_notify
            if send_bot_notify(target, content):
                crm.update_notification_status(notification_id, "sent")
                logger.info("通知已投递给 %s", target)
            else:
                crm.update_notification_status(notification_id, "failed")
                logger.error("通知投递失败: %s", target)
        except Exception as e:
            crm.update_notification_status(notification_id, "failed")
            logger.error("通知投递异常: %s", e)

    return notification_id
