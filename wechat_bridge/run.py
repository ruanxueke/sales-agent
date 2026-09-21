"""个人微信桥接主循环：读取、上报、轮询任务、草稿或发送、回执。"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wechat_bridge.audit import AuditLogger, LocalState
from wechat_bridge.binding import (
    describe as describe_binding,
    resolve_instance,
)
from wechat_bridge.central_client import CentralClient
from wechat_bridge.config import BridgeConfig, TargetConfig
from wechat_bridge.durable_queue import DurableQueue
from wechat_bridge.message_filter import contains_handover_keyword, normalize_message
from wechat_bridge.notifier import DesktopNotifier
from wechat_bridge.reader_adapter import CaptureReader
from wechat_bridge.runtime_lock import AlreadyRunningError, RuntimeLock
from wechat_bridge.ui_sender import WechatUiSender

logger = logging.getLogger("wechat_bridge")
BRIDGE_AGENT_VERSION = "2026.09.15.1"


class WechatBridge:
    def __init__(self, config: BridgeConfig, dry_run: bool | None = None):
        self.config = config
        self.dry_run = config.dry_run if dry_run is None else dry_run
        self.state = LocalState(config.state_path)
        self.audit = AuditLogger(config.audit_path)
        self.queue = DurableQueue(
            config.queue_path or Path(config.state_path).parent / "queue.db"
        )
        self.central = CentralClient(config)
        # 读取器按需构建：本机微信数据未解密、缺依赖、账号未就绪等情况下
        # 不能让整个桥接进程直接退出——那样控制台只剩「离线」，看不到任何原因。
        # 改为构建失败也能起心跳，把真实原因报到控制台的「最近错误」。
        self.reader = None
        self.reader_error = ""
        self._reader_retry_after = 0.0
        self.sender = WechatUiSender(config)
        self.notifier = DesktopNotifier(
            enabled=config.notify_on_message,
            sound=config.notification_sound,
        )
        self._last_message_at = ""
        self._last_reply_at = ""
        self._last_error = ""
        self._wechat_login_detected = False
        self._wechat_login_detail = {}
        self.instance_bind_status = ""
        self._started_at = int(time.time()) - 2
        self._synced_contact_names: dict[str, str] = {}

    def _ensure_reader(self) -> bool:
        """按需构建读取器。失败返回 False，并把原因存进 self.reader_error。"""
        if self.reader is not None:
            return True
        now = time.time()
        if now < self._reader_retry_after:
            return False
        try:
            self.reader = CaptureReader(self.config)
        except Exception as exc:
            self.reader = None
            self.reader_error = str(exc)
            self._reader_retry_after = now + 30  # 每 30 秒重试一次，避免空转扫盘
            return False
        self.reader_error = ""
        self._reader_retry_after = 0.0
        # 读取器实际解析出的账号回写配置，心跳才能把真实账号报给控制台，
        # 否则配置里 account_id 为空时界面「微信账号」永远显示 "-"。
        account = getattr(self.reader, "account", None)
        resolved = str(getattr(account, "name", "") or "")
        if resolved:
            self.config.account_id = resolved
        # 把 instance_id 与本机实际登录的微信账号绑定：
        # 同一个 instance 换账号时，中台会按 claimed_by=instance_id 回执任务，
        # 不加以区分就会出现「A 账号的回复被 B 账号确认掉」。详见 binding.py。
        effective, bind_status = resolve_instance(
            self.config.instance_id,
            self.config.account_id,
            self.config.instance_binding_path,
            allow_rebind=self.config.allow_instance_rebind,
        )
        self.instance_bind_status = bind_status
        if effective != self.config.instance_id:
            self.config.instance_id = effective
            self.central.config.instance_id = effective
        logger.info(
            "读取器就绪 account=%s source=%s instance=%s binding=%s",
            resolved or "-",
            getattr(self.reader, "account_source", ""),
            self.config.instance_id,
            bind_status,
        )
        return True

    def check(self) -> dict:
        self._sync_server_settings()
        if not self._ensure_reader():
            return {
                "bridge": "ok",
                "dry_run": self.dry_run,
                "recognition_enabled": self.config.recognition_enabled,
                "runtime_status": "need_setup",
                "reader_error": self.reader_error,
                "queue": (
                    getattr(self, "queue", None).metrics()
                    if getattr(self, "queue", None)
                    else {}
                ),
                "central": self.central.health(),
                "wechat": {"ok": False, "error": self.reader_error},
            }
        if self.config.detect_wechat_login:
            login = self.reader.detect_wechat_login()
            self._wechat_login_detected = bool(login.get("logged_in"))
        else:
            login = {"logged_in": False, "skipped": True}
            self._wechat_login_detected = False
        self._wechat_login_detail = login
        runtime_status = "paused" if not self.config.recognition_enabled else (
            "running" if self._wechat_login_detected else "waiting_wechat"
        )
        result = {
            "bridge": "ok",
            "dry_run": self.dry_run,
            "recognition_enabled": self.config.recognition_enabled,
            "runtime_status": runtime_status,
            "central": self.central.health(),
            "wechat": self.reader.health(),
            "wechat_login": login,
        }
        try:
            result["heartbeat"] = self.central.heartbeat(
                self._heartbeat_payload(status=runtime_status)
            )
        except Exception as exc:
            result["heartbeat"] = {"ok": False, "error": str(exc)}
        return result

    def process_messages(self, targets: list[TargetConfig] | None = None) -> dict:
        sent = 0
        duplicates = 0
        ignored = 0
        errors = []
        self.sync_all_contact_names()
        self._flush_pending_events()
        process_targets = list(targets or self.config.targets)
        known_usernames = {target.target_username for target in process_targets}
        if self.config.auto_discover_contacts:
            since = int(time.time()) - self.config.initial_scan_lookback_seconds
            for session in self.reader.list_customer_sessions(since=since):
                if session["username"] in known_usernames:
                    for target in process_targets:
                        if target.target_username == session["username"]:
                            target.target_name = session["name"]
                    continue
                process_targets.append(
                    TargetConfig(
                        target_type="contact",
                        target_name=session["name"],
                        target_username=session["username"],
                        enabled=True,
                        mode=self.config.default_contact_mode,
                    )
                )
                known_usernames.add(session["username"])

        self._sync_contact_names(process_targets)

        for target in process_targets:
            if not target.enabled or target.mode == "off":
                continue
            target_key = f"{self.config.account_id}:{target.target_username}"
            try:
                if not self.state.target_initialized(target_key):
                    baseline_rows = self.reader.read_messages(
                        target,
                        lookback_seconds=self.config.initial_scan_lookback_seconds,
                        limit=2000,
                    )
                    baseline_count = 0
                    rows = []
                    for raw in baseline_rows:
                        baseline = normalize_message(raw, self.config, target)
                        if baseline is None:
                            continue
                        if int(baseline.get("created_at") or 0) >= self._started_at:
                            rows.append(raw)
                            continue
                        self.state.mark_message(baseline["message_id"])
                        baseline_count += 1
                    self.state.mark_target_initialized(target_key)
                    self.audit.log(
                        "baseline_initialized",
                        target=target.target_name,
                        messages=baseline_count,
                    )
                else:
                    rows = self.reader.read_messages(target)
            except Exception as exc:
                errors.append({"target": target.target_name, "error": str(exc)})
                continue
            for raw in rows:
                event = normalize_message(raw, self.config, target)
                if event is None:
                    ignored += 1
                    continue
                fingerprint = event["message_id"]
                if self.state.seen_message(fingerprint):
                    duplicates += 1
                    continue
                self.queue.put_event(event)
                try:
                    result = self.central.send_event(event)
                except Exception as exc:
                    self.queue.fail_event(fingerprint, str(exc))
                    errors.append(
                        {
                            "target": target.target_name,
                            "message_id": fingerprint,
                            "error": str(exc),
                        }
                    )
                    continue
                if result.get("ok"):
                    self.queue.complete_event(fingerprint)
                    self.state.mark_message(fingerprint)
                    sent += 1
                    if not result.get("deduped"):
                        self.notifier.notify(
                            "微信新消息",
                            f"{target.target_name}: {event['content'][:90]}",
                        )
                    self.audit.log(
                        "event_sent",
                        target=target.target_name,
                        message_id=fingerprint,
                        task_id=result.get("task_id") or "",
                        deduped=bool(result.get("deduped")),
                    )
                else:
                    self.queue.fail_event(
                        fingerprint,
                        result.get("error") or "cloud rejected event",
                    )
                    errors.append(
                        {
                            "target": target.target_name,
                            "message_id": fingerprint,
                            "error": result.get("error") or "中台拒绝事件",
                        }
                    )
        return {"sent": sent, "duplicates": duplicates, "ignored": ignored, "errors": errors}

    def _flush_pending_events(self) -> None:
        for item in self.queue.pending_events(limit=20):
            message_id = item["message_id"]
            event = item["event"]
            try:
                result = self.central.send_event(event)
            except Exception as exc:
                self.queue.fail_event(message_id, str(exc))
                continue
            if result.get("ok"):
                self.queue.complete_event(message_id)
                self.state.mark_message(message_id)
            else:
                self.queue.fail_event(
                    message_id,
                    result.get("error") or "cloud rejected event",
                )

    def sync_all_contact_names(self) -> None:
        if not self.config.auto_discover_contacts or self.reader is None:
            return
        try:
            sessions = self.reader.list_customer_sessions(
                since=None,
                limit=5000,
            )
        except Exception as exc:
            logger.warning("客户备注名称巡检失败: %s", exc)
            return
        self._sync_contact_names(
            [
                TargetConfig(
                    target_type="contact",
                    target_name=session["name"],
                    target_username=session["username"],
                    enabled=True,
                    mode=self.config.default_contact_mode,
                )
                for session in sessions
            ]
        )

    def _sync_contact_names(self, targets: list[TargetConfig]) -> None:
        cache = getattr(self, "_synced_contact_names", None)
        if cache is None:
            cache = {}
            self._synced_contact_names = cache
        pending = []
        for target in targets:
            username = str(target.target_username or "").strip()
            name = str(target.target_name or "").strip()
            if not username or not name:
                continue
            key = f"{self.config.account_id}:{username}"
            if cache.get(key) == name:
                continue
            pending.append(
                {
                    "target_username": username,
                    "target_name": name,
                }
            )
        if not pending:
            return
        try:
            result = self.central.sync_contact_names(pending)
        except Exception as exc:
            logger.warning("客户备注名称同步失败: %s", exc)
            return
        if not result.get("ok"):
            logger.warning("客户备注名称同步被拒绝: %s", result)
            return
        for item in pending:
            key = f"{self.config.account_id}:{item['target_username']}"
            cache[key] = item["target_name"]
        self.audit.log(
            "contact_names_synced",
            count=len(pending),
            updated=result.get("updated") or 0,
        )

    def process_tasks(self) -> dict:
        claimed = self.central.get_tasks(claim=not self.dry_run)
        task_map: dict[str, dict] = {}
        for task in claimed:
            task_id = str(task.get("task_id") or "").strip()
            if not task_id:
                continue
            self.queue.put_task(task)
            task_map[task_id] = task
        for task in self.queue.recoverable_tasks(limit=100):
            task_id = str(task.get("task_id") or "").strip()
            if task_id and task_id not in task_map:
                task_map[task_id] = task

        drafted = 0
        sent = 0
        failed = 0
        skipped = 0
        for task in task_map.values():
            task_id = str(task.get("task_id") or "").strip()
            if not task_id:
                continue
            local = self.queue.get_task(task_id) or {}
            local_status = str(local.get("local_status") or "")
            last_stage = str(local.get("last_stage") or "")
            if self.state.task_status(task_id) or local_status == "completed":
                skipped += 1
                continue
            if local_status in {"manual_review", "dead_letter"}:
                skipped += 1
                continue

            target = self.config.target_for(
                target_name=task.get("target_name") or "",
                target_username=task.get("target_username") or "",
            )
            if (
                target is None
                and self.config.auto_discover_contacts
                and str(task.get("target_type") or "contact") == "contact"
                and str(task.get("target_username") or "")
                not in set(self.config.excluded_usernames)
            ):
                target = TargetConfig(
                    target_type="contact",
                    target_name=str(task.get("target_name") or ""),
                    target_username=str(task.get("target_username") or ""),
                    enabled=True,
                    mode=self.config.default_contact_mode,
                )
            if target is None or not target.enabled or target.mode == "off":
                self.queue.update_task(task_id, status="completed", stage="target_disabled")
                if not self.dry_run:
                    self.central.ack_task(task_id, "skipped", "target disabled")
                skipped += 1
                continue

            if local_status == "awaiting_receipt" or last_stage in {
                "before_enter",
                "entered",
            }:
                if self._recover_uncertain_task(task, target):
                    sent += 1
                else:
                    failed += 1
                continue

            content = str(task.get("content") or "").strip()
            if not content:
                self.queue.update_task(task_id, status="completed", stage="empty_content")
                if not self.dry_run:
                    self.central.ack_task(task_id, "skipped", "empty content")
                skipped += 1
                continue
            if contains_handover_keyword(content, target):
                self.queue.update_task(task_id, status="completed", stage="handover")
                if not self.dry_run:
                    self.central.ack_task(task_id, "handover", "handover keyword")
                self.audit.log("handover", task_id=task_id, target=target.target_name)
                continue
            if self.dry_run:
                self.audit.log(
                    "dry_run_task",
                    task_id=task_id,
                    target=target.target_name,
                    mode=target.mode,
                    content=content[:200],
                )
                continue

            target_key = f"{self.config.account_id}:{target.target_username}"
            if target.mode == "auto":
                allowed, reason = self.state.allow_send(
                    target_key,
                    target.daily_limit,
                    target.hourly_limit,
                )
                if not allowed:
                    self.queue.update_task(
                        task_id,
                        status="completed",
                        stage="rate_limited",
                        error=reason,
                    )
                    self.central.ack_task(task_id, "skipped", reason)
                    self.audit.log(
                        "task_rate_limited",
                        task_id=task_id,
                        target=target.target_name,
                        reason=reason,
                    )
                    skipped += 1
                    continue

            attempt_count = int(local.get("local_attempt_count") or 0) + 1
            self.queue.update_task(
                task_id,
                status="processing",
                stage="resolving",
                attempt_count=attempt_count,
                next_attempt_at="",
                error="",
            )

            def on_stage(stage: str) -> None:
                self.queue.update_task(
                    task_id,
                    status="processing",
                    stage=stage,
                )

            result = self._send_with_retry(task, target, on_stage=on_stage)
            self.audit.log(
                "task_ui_result",
                task_id=task_id,
                target=target.target_name,
                mode=target.mode,
                status=result.status,
                detail=result.detail,
            )
            if result.ok and result.status == "sent":
                self.queue.update_task(
                    task_id,
                    status="awaiting_receipt",
                    stage="entered",
                )
                if self.config.verify_send_with_reader and not self._verify_sent(task, target):
                    detail = "sent but WeChat receipt was not confirmed"
                    self.queue.update_task(
                        task_id,
                        status="manual_review",
                        stage="awaiting_receipt",
                        error=detail,
                    )
                    self.central.ack_task(
                        task_id,
                        "manual_review",
                        detail,
                        failure_code="SEND_UNCONFIRMED",
                        failure_stage="awaiting_receipt",
                    )
                    failed += 1
                    continue
                self.queue.update_task(task_id, status="completed", stage="sent")
                self.state.record_send(target_key)
                if self.config.notify_on_send:
                    self.notifier.notify("自动回复已发送", target.target_name)
                self.state.mark_task(task_id, "sent")
                self.central.ack_task(task_id, "sent", result.detail)
                sent += 1
                continue

            if result.ok:
                self.queue.update_task(
                    task_id,
                    status="completed",
                    stage=result.status,
                )
                self.state.mark_task(task_id, result.status)
                self.central.ack_task(task_id, result.status, result.detail)
                if result.status == "drafted":
                    drafted += 1
                continue

            failure_code = (
                getattr(result, "failure_code", "")
                or self._classify_send_failure(result.detail)
            )
            if failure_code in {"RETRYABLE_UI", "WINDOW_FOCUS_LOST"}:
                delay = min(300, 5 * (2 ** max(0, attempt_count - 1)))
                next_retry = (
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + delay))
                )
                self.queue.update_task(
                    task_id,
                    status="retry_wait",
                    stage="send_failed",
                    next_attempt_at=next_retry,
                    error=result.detail,
                )
                ack_status = "failed"
            else:
                self.queue.update_task(
                    task_id,
                    status="manual_review",
                    stage="send_failed",
                    error=result.detail,
                )
                ack_status = "manual_review"
            self.central.ack_task(
                task_id,
                ack_status,
                result.detail,
                failure_code=failure_code,
                failure_stage="send",
                diagnostic_path=getattr(result, "diagnostic_path", ""),
            )
            failed += 1

        return {
            "claimed": len(task_map),
            "drafted": drafted,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
        }

    def _recover_uncertain_task(self, task: dict, target: TargetConfig) -> bool:
        task_id = str(task.get("task_id") or "")
        if self._verify_sent(task, target):
            self.queue.update_task(task_id, status="completed", stage="sent")
            self.state.mark_task(task_id, "sent")
            self.central.ack_task(task_id, "sent", "recovered from receipt verification")
            return True
        detail = "uncertain send state; receipt not found"
        self.queue.update_task(
            task_id,
            status="manual_review",
            stage="recovery",
            error=detail,
        )
        self.central.ack_task(
            task_id,
            "manual_review",
            detail,
            failure_code="SEND_UNCONFIRMED",
            failure_stage="recovery",
        )
        return False

    @staticmethod
    def _classify_send_failure(detail: str) -> str:
        text = str(detail or "")
        if "前台" in text or "焦点" in text or "window" in text.lower():
            return "WINDOW_FOCUS_LOST"
        if "搜索结果" in text or "精确匹配" in text:
            return "TARGET_NOT_FOUND"
        if "标题" in text or "会话" in text:
            return "RETRYABLE_UI"
        return "RETRYABLE_UI"

    def _process_tasks_legacy(self) -> dict:
        tasks = self.central.get_tasks(claim=not self.dry_run)
        drafted = 0
        sent = 0
        failed = 0
        skipped = 0
        for task in tasks:
            task_id = str(task.get("task_id") or "")
            if not task_id:
                continue
            if self.state.task_status(task_id):
                skipped += 1
                continue
            target = self.config.target_for(
                target_name=task.get("target_name") or "",
                target_username=task.get("target_username") or "",
            )
            if (
                target is None
                and self.config.auto_discover_contacts
                and str(task.get("target_type") or "contact") == "contact"
                and str(task.get("target_username") or "")
                not in set(self.config.excluded_usernames)
            ):
                target = TargetConfig(
                    target_type="contact",
                    target_name=str(task.get("target_name") or ""),
                    target_username=str(task.get("target_username") or ""),
                    enabled=True,
                    mode=self.config.default_contact_mode,
                )
            if target is None or not target.enabled or target.mode == "off":
                skipped += 1
                if not self.dry_run:
                    self.central.ack_task(task_id, "skipped", "目标未启用或不在白名单")
                continue
            content = str(task.get("content") or "").strip()
            if not content:
                skipped += 1
                if not self.dry_run:
                    self.central.ack_task(task_id, "skipped", "任务回复为空")
                continue
            if contains_handover_keyword(content, target):
                if not self.dry_run:
                    self.central.ack_task(task_id, "handover", "命中转人工关键词")
                self.audit.log("handover", task_id=task_id, target=target.target_name)
                continue
            if self.dry_run:
                self.audit.log(
                    "dry_run_task",
                    task_id=task_id,
                    target=target.target_name,
                    mode=target.mode,
                    content=content[:200],
                )
                continue

            if target.mode == "auto":
                target_key = f"{self.config.account_id}:{target.target_username}"
                allowed, reason = self.state.allow_send(
                    target_key,
                    target.daily_limit,
                    target.hourly_limit,
                )
                if not allowed:
                    self.central.ack_task(task_id, "skipped", reason)
                    self.audit.log(
                        "task_rate_limited",
                        task_id=task_id,
                        target=target.target_name,
                        reason=reason,
                    )
                    skipped += 1
                    continue

            result = self._send_with_retry(task, target)
            self.audit.log(
                "task_ui_result",
                task_id=task_id,
                target=target.target_name,
                mode=target.mode,
                status=result.status,
                detail=result.detail,
            )
            if result.ok and result.status == "sent" and self.config.verify_send_with_reader:
                verified = self._verify_sent(task, target)
                if not verified:
                    detail = "已执行发送，但回读微信数据库未确认，已停止重试"
                    self.central.ack_task(task_id, "failed", detail)
                    self.audit.log(
                        "task_verify_failed",
                        task_id=task_id,
                        target=target.target_name,
                    )
                    failed += 1
                    continue
            if result.ok:
                if result.status == "sent":
                    self.state.record_send(target_key)
                    if self.config.notify_on_send:
                        self.notifier.notify("自动回复已发送", target.target_name)
                self.state.mark_task(task_id, result.status)
                self.central.ack_task(task_id, result.status, result.detail)
                if result.status == "drafted":
                    drafted += 1
                elif result.status == "sent":
                    sent += 1
            else:
                self.central.ack_task(task_id, "failed", result.detail)
                failed += 1
        return {
            "claimed": len(tasks),
            "drafted": drafted,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
        }

    def _send_with_retry(
        self,
        task: dict,
        target: TargetConfig,
        on_stage=None,
    ):
        attempts = max(1, int(self.config.send_retry_attempts))
        delay = max(0.5, float(self.config.send_retry_backoff_seconds))
        result = None
        for attempt in range(1, attempts + 1):
            result = self.sender.send(task, target.mode, on_stage=on_stage)
            if result.ok:
                if attempt > 1:
                    self.audit.log(
                        "task_send_retry_ok",
                        task_id=task.get("task_id") or "",
                        target=target.target_name,
                        attempt=attempt,
                    )
                return result
            if attempt >= attempts:
                break
            self.audit.log(
                "task_send_retry",
                task_id=task.get("task_id") or "",
                target=target.target_name,
                attempt=attempt,
                detail=result.detail,
            )
            time.sleep(delay * attempt)
        return result

    def _verify_sent(self, task: dict, target: TargetConfig) -> bool:
        started = time.time()
        since = int(started) - 5
        deadline = started + max(3, self.config.verify_send_timeout_seconds)
        while time.time() < deadline:
            try:
                if self.reader.find_outgoing(
                    target,
                    task.get("content") or "",
                    since=since,
                ):
                    return True
            except Exception as exc:
                self.audit.log(
                    "send_verify_error",
                    task_id=task.get("task_id") or "",
                    target=target.target_name,
                    error=str(exc)[:200],
                )
            time.sleep(2)
        return False

    def run_once(self) -> dict:
        self._sync_server_settings()
        empty_result = {
            "messages": {"sent": 0, "duplicates": 0, "ignored": 0, "errors": []},
            "tasks": {"claimed": 0, "drafted": 0, "sent": 0, "failed": 0, "skipped": 0},
        }

        # 读取器不可用（未解密 / 缺依赖 / 无账号）不是致命错误：
        # 保持心跳把原因上报，控制台才能给出可操作提示。
        if not self._ensure_reader():
            self._last_error = self.reader_error
            self._wechat_login_detected = False
            self._wechat_login_detail = {
                "logged_in": False,
                "reason": "reader_unavailable",
                "error": self.reader_error,
            }
            result = dict(empty_result, paused=True, reason="reader_unavailable")
            result["reader_error"] = self.reader_error
            self._heartbeat_safe(result, status="need_setup")
            return result

        # 登录检测放在识别开关之前：即使「开始识别」关着，
        # 控制台也应该能显示本机微信到底登录没登录。
        if self.config.detect_wechat_login:
            login = self.reader.detect_wechat_login()
            self._wechat_login_detected = bool(login.get("logged_in"))
        else:
            login = {"logged_in": False, "skipped": True}
            self._wechat_login_detected = False
        self._wechat_login_detail = login
        self.sync_all_contact_names()

        if not self.config.recognition_enabled:
            self._last_error = ""
            result = dict(empty_result, paused=True, reason="recognition_disabled")
            result["wechat_login"] = login
            self._heartbeat_safe(result, status="paused")
            return result

        if self.config.detect_wechat_login and not self._wechat_login_detected:
            self._last_error = ""
            result = dict(empty_result, paused=True, reason="wechat_not_logged_in")
            result["wechat_login"] = login
            self._heartbeat_safe(result, status="waiting_wechat")
            return result

        messages = self.process_messages()
        tasks = self.process_tasks()
        result = {
            "messages": messages,
            "tasks": tasks,
        }
        if messages.get("sent"):
            self._last_message_at = time.strftime("%Y-%m-%d %H:%M:%S")
        if tasks.get("sent") or tasks.get("drafted"):
            self._last_reply_at = time.strftime("%Y-%m-%d %H:%M:%S")
        errors = []
        if messages.get("errors"):
            errors.extend(str(item) for item in messages["errors"])
        self._last_error = " | ".join(errors)[:1000]
        self._heartbeat_safe(result, status="degraded" if errors else "running")
        return result

    def _heartbeat_safe(self, result: dict | None, status: str) -> None:
        try:
            self.central.heartbeat(self._heartbeat_payload(result=result, status=status))
        except Exception as exc:
            logger.warning("桥接心跳上报失败: %s", exc)

    def _heartbeat_payload(
        self,
        result: dict | None = None,
        status: str = "running",
    ) -> dict:
        modes = {target.mode for target in self.config.targets}
        mode = self.config.default_contact_mode
        if len(modes) == 1:
            mode = next(iter(modes))
        elif modes:
            mode = "mixed"
        return {
            "tenant_id": self.config.tenant_id,
            "instance_id": self.config.instance_id,
            "account_id": self.config.account_id,
            "status": status,
            "mode": mode,
            "auto_discover_contacts": self.config.auto_discover_contacts,
            "notify_on_message": self.config.notify_on_message,
            "wechat_login_detected": self._wechat_login_detected,
            "poll_interval_seconds": self.config.poll_interval_seconds,
            "last_message_at": self._last_message_at,
            "last_reply_at": self._last_reply_at,
            "last_error": self._last_error,
            "detail": {
                "dry_run": self.dry_run,
                "agent_version": BRIDGE_AGENT_VERSION,
                "target_count": len(self.config.targets),
                "recognition_enabled": self.config.recognition_enabled,
                "detect_wechat_login": self.config.detect_wechat_login,
                "wechat_login": self._wechat_login_detail,
                "reader_ready": self.reader is not None,
                "account_source": getattr(self.reader, "account_source", ""),
                "reader_error": self.reader_error,
                # 实例与微信账号的绑定情况：控制台据此区分「没识别到账号」和
                # 「识别到了但与上次绑定的不是同一个账号」。
                "instance_binding": describe_binding(
                    self.config.instance_id,
                    self.config.account_id,
                    self.config.instance_binding_path,
                ),
                "instance_bind_status": self.instance_bind_status,
                "result": result or {},
            },
        }

    def _sync_server_settings(self) -> None:
        try:
            result = self.central.get_settings()
            settings = result.get("settings") or {}
            if "detect_wechat_login" in settings:
                self.config.detect_wechat_login = bool(
                    settings["detect_wechat_login"]
                )
            if "recognition_enabled" in settings:
                self.config.recognition_enabled = bool(
                    settings["recognition_enabled"]
                )
            if "notify_on_message" in settings:
                self.config.notify_on_message = bool(
                    settings["notify_on_message"]
                )
                self.notifier.enabled = self.config.notify_on_message
        except Exception as exc:
            logger.debug("桥接设置同步失败，使用本地配置: %s", exc)

    def run_forever(self) -> None:
        logger.info(
            "个人微信桥接已启动 dry_run=%s account=%s recognition=%s",
            self.dry_run,
            self.config.account_id,
            self.config.recognition_enabled,
        )
        consecutive_failures = 0
        while True:
            try:
                result = self.run_once()
                consecutive_failures = 0
                if any(result["messages"].values()):
                    logger.info("桥接轮询: %s", result)
            except KeyboardInterrupt:
                return
            except Exception:
                consecutive_failures += 1
                logger.exception("桥接轮询失败")
            if consecutive_failures:
                delay = min(
                    60.0,
                    max(1.0, self.config.poll_interval_seconds)
                    * (2 ** min(consecutive_failures, 5)),
                )
            else:
                delay = max(1.0, self.config.poll_interval_seconds)
            time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser(description="个人微信读取与中台回复桥接")
    parser.add_argument("--config", default="", help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="执行一次后退出")
    parser.add_argument("--check", action="store_true", help="只做环境和中台连通检查")
    parser.add_argument("--live-draft", action="store_true", help="允许写入微信草稿")
    parser.add_argument("--notify-test", action="store_true", help="测试 Windows 新消息提醒")
    parser.add_argument("--send-events-only", action="store_true", help="只上报消息，不拉取任务")
    parser.add_argument(
        "--version",
        action="version",
        version=BRIDGE_AGENT_VERSION,
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = BridgeConfig.load(args.config or None)
    dry_run = False if args.live_draft else config.dry_run
    bridge = WechatBridge(config, dry_run=dry_run)
    if args.notify_test:
        bridge.notifier.notify("销售智能体测试", "新消息提醒功能正常")
        print({"ok": True, "notification": "sent"})
        return 0
    if args.check:
        print(bridge.check())
        return 0
    if args.send_events_only:
        print(bridge.process_messages())
        return 0
    if args.once:
        print(bridge.run_once())
        return 0
    lock_path = Path(config.state_path).parent / "bridge.lock"
    try:
        with RuntimeLock(lock_path):
            bridge.run_forever()
    except AlreadyRunningError as exc:
        logger.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
