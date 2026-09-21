"""视觉受管执行器主循环：心跳 -> 主动触达任务 -> 未读扫描 -> 去重 -> 获取回复 -> 模拟发送。

运行方式：在企业微信/个人微信 PC 已登录的 Windows 桌面运行本模块。
安全策略：未配置视觉模型、命中风控、超出发送上限、熔断时自动暂停，不做盲目操作。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time

from . import config
from .api_client import VisionApi
from .controller import Controller
from .risk import RiskGuard
from .state import LocalState
from .vision import analyze_screenshot

os.makedirs(config.DATA_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(config.DATA_DIR, "vision_agent_worker.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("vision_agent.worker")


def _fingerprint(contact: str, sender: str, content: str, msg_time: str = "", y: int = 0) -> str:
    raw = f"{contact}|{sender}|{content}|{msg_time}|{y}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _find_contact(controller: Controller, vision: dict, name: str):
    if not name:
        return None
    for item in vision.get("contacts") or []:
        item_name = (item.get("name") or "").strip()
        if item_name and (item_name == name or name in item_name or item_name in name):
            return item
    return None


def _open_contact(controller: Controller, vision: dict, name: str) -> bool:
    item = _find_contact(controller, vision, name)
    if item:
        controller.click(int(item["x"]), int(item["y"]))
        return True
    search = vision.get("search_box") or {}
    if search.get("x") and search.get("y"):
        controller.click(int(search["x"]), int(search["y"]))
        controller.type_text(name)
        time.sleep(1.2)
        return True
    return False


def _last_incoming(vision: dict) -> dict:
    messages = vision.get("messages") or []
    if not messages:
        return vision.get("last_incoming") or {}
    for m in reversed(messages):
        sender = (m.get("sender") or "").strip()
        content = (m.get("content") or "").strip()
        if content and sender not in ("我", "自己", ""):
            return m
    return vision.get("last_incoming") or {}


def _group_allowed(vision: dict, content: str) -> bool:
    if not vision.get("is_group"):
        return True
    text = content or ""
    return any(k and k in text for k in config.GROUP_TRIGGER_KEYWORDS)


def _process_task(api: VisionApi, controller: Controller, risk: RiskGuard, task: dict) -> None:
    contact = (task.get("contact") or "").strip()
    content = (task.get("content") or "").strip()
    if not contact or not content:
        api.complete_task(task["id"], "failed", note="缺少联系人或内容")
        return
    if risk.circuit_break(contact + " " + content):
        api.audit("circuit_break", {"task_id": task["id"], "contact": contact})
        api.pause(True)
        api.complete_task(task["id"], "failed", note="本地熔断")
        return
    ok, reason = risk.check_send()
    if not ok:
        api.audit("rate_limited", {"task_id": task["id"], "reason": reason})
        api.complete_task(task["id"], "skipped", note=reason)
        return
    image = controller.screenshot()
    vision = analyze_screenshot(image) if image else {}
    if not _open_contact(controller, vision, contact):
        api.audit("task_contact_not_found", {"task_id": task["id"], "contact": contact})
        api.complete_task(task["id"], "failed", note="未在会话列表中找到联系人")
        return
    time.sleep(0.8)
    image = controller.screenshot()
    vision = analyze_screenshot(image) if image else {}
    input_box = vision.get("input_box") or {}
    if config.DEBUG_NO_SEND:
        logger.info("[演练] 主动触达 %s: %s", contact, content[:50])
        api.audit("task_dry_run", {"task_id": task["id"], "contact": contact})
        api.complete_task(task["id"], "sent", note="演练模式，未实际发送")
        risk.record_success()
        return
    controller.type_and_send(content, input_box, config.REPLY_MIN_DELAY, config.REPLY_MAX_DELAY)
    api.record_send(1)
    api.audit("task_sent", {"task_id": task["id"], "contact": contact, "content": content[:80]})
    api.complete_task(task["id"], "sent", note="")
    risk.record_success()


def _process_incoming(api: VisionApi, controller: Controller, risk: RiskGuard, state: LocalState, vision: dict) -> None:
    contact = (vision.get("current_contact") or "").strip()
    if not contact:
        return
    if contact in config.IGNORE_CONTACTS:
        return
    if state.is_human(contact):
        return
    last = _last_incoming(vision)
    content = (last.get("content") or "").strip()
    sender = (last.get("sender") or "").strip()
    if not content or sender in ("我", "自己", ""):
        return
    if not _group_allowed(vision, content):
        return
    fp = _fingerprint(contact, sender, content, last.get("time") or "", int(last.get("y") or 0))
    if state.seen_local(fp):
        return
    seen = api.mark_seen(fp)
    if not seen.get("was_new"):
        state.remember(fp)
        return
    state.remember(fp)
    if state.in_cooldown(contact):
        return
    ok, reason = risk.check_text(content)
    if not ok:
        api.audit("blocked_text", {"contact": contact, "content": content[:50], "reason": reason})
        return
    reply_data = api.get_reply(content, session_id=f"vision_{config.MODE}:{contact}", contact=contact)
    if not reply_data.get("ok") or not reply_data.get("reply"):
        return
    reply = reply_data["reply"]
    ok, reason = risk.check_send()
    if not ok:
        api.audit("rate_limited", {"contact": contact, "reason": reason})
        return
    api.audit("will_reply", {"contact": contact, "content": content[:80], "reply": reply[:80]})
    if config.DEBUG_NO_SEND:
        logger.info("[演练] 回复 %s: %s", contact, reply[:50])
        api.audit("dry_run_reply", {"contact": contact, "reply": reply[:80]})
        state.set_cooldown(contact, 30)
        risk.record_success()
        return
    input_box = vision.get("input_box") or {}
    controller.type_and_send(reply, input_box, config.REPLY_MIN_DELAY, config.REPLY_MAX_DELAY)
    api.record_send(1)
    api.audit("sent", {"contact": contact, "content": content[:50], "reply": reply[:80]})
    state.set_cooldown(contact, 60)
    risk.record_success()
    if reply_data.get("handover"):
        state.set_human(contact, True)


def run_once(api: VisionApi, controller: Controller, risk: RiskGuard, state: LocalState) -> None:
    status = api.status()
    if status.get("paused") or status.get("status") in ("paused", "blocked"):
        return
    if not status.get("enabled"):
        logger.info("视觉执行器未启用，仅上报心跳"); return
    if risk.circuit_break(status.get("last_error") or ""):
        api.audit("circuit_break", {"reason": "检测到风控提示，自动暂停"})
        api.pause(True)
        return

    tasks = api.claim_tasks(limit=1)
    if tasks:
        _process_task(api, controller, risk, tasks[0])
        return

    image = controller.screenshot()
    if not image:
        return
    vision = analyze_screenshot(image)
    api.audit("scan", {"ok": bool(vision.get("ok")), "note": vision.get("note", "")})
    risk_text = vision.get("risk_warning") or ""
    if risk.circuit_break(risk_text):
        api.audit("circuit_break", {"reason": risk_text})
        api.pause(True)
        return
    if not vision.get("current_contact"):
        unread = [c for c in (vision.get("contacts") or []) if c.get("unread")]
        if unread:
            controller.click(int(unread[0]["x"]), int(unread[0]["y"]))
            time.sleep(0.8)
            image = controller.screenshot()
            if image:
                vision = analyze_screenshot(image)
    _process_incoming(api, controller, risk, state, vision)


def main_loop(stop_event=None) -> None:
    api = VisionApi()
    controller = Controller(config.SCREENSHOT_REGION)
    risk = RiskGuard(
        daily_limit=config.MAX_SENDS_PER_DAY,
        hourly_limit=60,
        minute_limit=5,
        consecutive_limit=config.MAX_CONSECUTIVE_SENDS,
    )
    state = LocalState()
    logger.info(
        "视觉受管执行器启动 instance=%s mode=%s controller=%s api=%s",
        config.INSTANCE_ID,
        config.MODE,
        controller.available,
        config.API_BASE,
    )
    if config.DEBUG_NO_SEND:
        logger.warning("演练模式已开启：只识别不发送")
    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("视觉执行器已停止"); break
        try:
            api.heartbeat(config.INSTANCE_ID, config.MODE)
            run_once(api, controller, risk, state)
        except Exception as e:
            logger.error("执行器异常: %s", e)
            api.audit("error", {"error": str(e)[:200]})
        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main_loop()
