"""本地桥接配置加载。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import logging
logger = logging.getLogger(__name__)



def _read_project_api_key() -> str:
    """开发期兜底：从项目根 .env 读第一个 API Key。

    只在「非安装包运行」时生效——安装后的桥接跑在 resources/wechat_bridge/ 下，
    此时禁止回读上一级，避免把开发者自己的 .env 带进客户环境。
    """
    parent = Path(__file__).resolve().parent.parent
    if parent.name.lower() == "resources":
        return ""
    env_file = parent / ".env"
    try:
        for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "API_KEYS":
                return value.split(",", 1)[0].strip()
    except OSError as e:
        logger.debug("_read_project_api_key 异常已忽略: %s", e)
    return ""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class TargetConfig:
    target_type: str = "contact"
    target_name: str = ""
    target_username: str = ""
    enabled: bool = False
    mode: str = "draft"
    daily_limit: int = 30
    hourly_limit: int = 10
    min_reply_delay: float = 3
    max_reply_delay: float = 8
    handover_keywords: list[str] = field(
        default_factory=lambda: ["人工", "投诉", "转人工"]
    )
    require_mention: bool = True


@dataclass
class BridgeConfig:
    central_base_url: str = "http://127.0.0.1:5000"
    api_key: str = ""
    tenant_id: int = 0
    account_id: str = ""
    instance_id: str = "local-wechat"
    capture_script: str = ""
    wechat_files_root: str = ""
    poll_interval_seconds: float = 10
    message_lookback_seconds: int = 300
    initial_scan_lookback_seconds: int = 86400
    request_timeout_seconds: float = 30
    request_connect_timeout_seconds: float = 5
    request_retry_total: int = 3
    request_retry_backoff_seconds: float = 0.5
    dry_run: bool = True
    auto_send_enabled: bool = False
    notify_on_message: bool = True
    notification_sound: bool = True
    notify_on_send: bool = False
    recognition_enabled: bool = False
    detect_wechat_login: bool = True
    auto_discover_contacts: bool = False
    default_contact_mode: str = "draft"
    excluded_usernames: list[str] = field(default_factory=list)
    decrypt_before_read: bool = True
    decrypt_interval_seconds: int = 30
    verify_send_with_reader: bool = True
    verify_send_timeout_seconds: int = 20
    send_retry_attempts: int = 3
    send_retry_backoff_seconds: float = 2
    allow_media_placeholders: bool = False
    self_names: list[str] = field(default_factory=list)
    self_usernames: list[str] = field(default_factory=list)
    targets: list[TargetConfig] = field(default_factory=list)
    window_title: str = "微信"
    search_template_path: str = ""
    template_match_threshold: float = 0.82
    verify_target_with_ocr: bool = True
    allow_unverified_target: bool = False
    input_x_ratio: float = 0.52
    input_bottom_offset: int = 58
    reply_max_length: int = 500
    state_path: str = ""
    audit_path: str = ""
    queue_path: str = ""
    # 实例与微信账号的绑定落盘位置（默认 data/instance_binding.json）
    instance_binding_path: str = ""
    # 允许同一 instance 改绑到别的微信账号。默认关闭：账号变了会先给
    # instance_id 加账号后缀，避免两个账号互相回执任务。
    allow_instance_rebind: bool = False

    @classmethod
    def load(cls, path: str | Path | None = None) -> "BridgeConfig":
        base_dir = Path(__file__).resolve().parent
        config_path = Path(path) if path else base_dir / "config.json"
        raw = {}
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
        elif (base_dir / "config.example.json").exists():
            raw = json.loads(
                (base_dir / "config.example.json").read_text(encoding="utf-8-sig")
            )

        data_dir = Path(os.getenv("WECHAT_BRIDGE_HOME") or base_dir / "data")

        def resolve_path(value: str) -> str:
            if not value:
                return ""
            candidate = Path(value).expanduser()
            if candidate.is_absolute():
                return str(candidate)
            return str((base_dir / candidate).resolve())

        values = {
            "central_base_url": raw.get("central_base_url") or os.getenv("CENTRAL_BASE_URL")
            or "http://127.0.0.1:5000",
            "api_key": raw.get("api_key") or "",
            "tenant_id": int(raw.get("tenant_id") or 0),
            "account_id": raw.get("account_id") or os.getenv("WECHAT_ACCOUNT_ID") or "",
            "instance_id": raw.get("instance_id")
            or os.getenv("WECHAT_BRIDGE_INSTANCE_ID")
            or "local-wechat",
            "capture_script": resolve_path(
                raw.get("capture_script") or os.getenv("WECHAT_CAPTURE_SCRIPT") or ""
            ),
            "wechat_files_root": str(
                raw.get("wechat_files_root")
                or os.getenv("WECHAT_FILES_ROOT")
                or ""
            ),
            "poll_interval_seconds": float(raw.get("poll_interval_seconds") or 10),
            "message_lookback_seconds": int(raw.get("message_lookback_seconds") or 300),
            "initial_scan_lookback_seconds": int(
                raw.get("initial_scan_lookback_seconds") or 86400
            ),
            "request_timeout_seconds": float(raw.get("request_timeout_seconds") or 30),
            "request_connect_timeout_seconds": float(
                raw.get("request_connect_timeout_seconds") or 5
            ),
            "request_retry_total": int(raw.get("request_retry_total") or 3),
            "request_retry_backoff_seconds": float(
                raw.get("request_retry_backoff_seconds") or 0.5
            ),
            "dry_run": bool(raw.get("dry_run", True)),
            "auto_send_enabled": bool(raw.get("auto_send_enabled", False)),
            "notify_on_message": bool(raw.get("notify_on_message", True)),
            "notification_sound": bool(raw.get("notification_sound", True)),
            "notify_on_send": bool(raw.get("notify_on_send", False)),
            "recognition_enabled": bool(raw.get("recognition_enabled", False)),
            "detect_wechat_login": bool(raw.get("detect_wechat_login", True)),
            "auto_discover_contacts": _env_bool(
                "WECHAT_BRIDGE_AUTO_DISCOVER",
                bool(raw.get("auto_discover_contacts", False)),
            ),
            "default_contact_mode": str(raw.get("default_contact_mode") or "draft"),
            "excluded_usernames": list(raw.get("excluded_usernames") or []),
            "decrypt_before_read": bool(raw.get("decrypt_before_read", True)),
            "decrypt_interval_seconds": int(raw.get("decrypt_interval_seconds") or 30),
            "verify_send_with_reader": bool(raw.get("verify_send_with_reader", True)),
            "verify_send_timeout_seconds": int(raw.get("verify_send_timeout_seconds") or 20),
            "send_retry_attempts": int(raw.get("send_retry_attempts") or 3),
            "send_retry_backoff_seconds": float(
                raw.get("send_retry_backoff_seconds") or 2
            ),
            "allow_media_placeholders": bool(raw.get("allow_media_placeholders", False)),
            "self_names": list(raw.get("self_names") or []),
            "self_usernames": list(raw.get("self_usernames") or []),
            "window_title": raw.get("window_title") or "微信",
            "search_template_path": resolve_path(
                raw.get("search_template_path") or ""
            ),
            "template_match_threshold": float(raw.get("template_match_threshold") or 0.82),
            "verify_target_with_ocr": bool(raw.get("verify_target_with_ocr", True)),
            "allow_unverified_target": bool(raw.get("allow_unverified_target", False)),
            "input_x_ratio": float(raw.get("input_x_ratio") or 0.52),
            "input_bottom_offset": int(raw.get("input_bottom_offset") or 58),
            "reply_max_length": int(raw.get("reply_max_length") or 500),
            "state_path": str(raw.get("state_path") or data_dir / "state.json"),
            "audit_path": str(raw.get("audit_path") or data_dir / "audit.jsonl"),
            "queue_path": str(raw.get("queue_path") or data_dir / "queue.db"),
            "instance_binding_path": str(
                raw.get("instance_binding_path") or data_dir / "instance_binding.json"
            ),
            "allow_instance_rebind": _env_bool(
                "WECHAT_BRIDGE_ALLOW_REBIND",
                bool(raw.get("allow_instance_rebind", False)),
            ),
        }

        api_key_env = str(raw.get("api_key_env") or "").strip()
        if api_key_env:
            values["api_key"] = os.getenv(api_key_env, values["api_key"])
        if not values["api_key"]:
            values["api_key"] = _read_project_api_key()

        targets = []
        for item in raw.get("targets") or []:
            targets.append(
                TargetConfig(
                    target_type=str(item.get("target_type") or "contact"),
                    target_name=str(item.get("target_name") or ""),
                    target_username=str(item.get("target_username") or ""),
                    enabled=bool(item.get("enabled", False)),
                    mode=str(item.get("mode") or "draft"),
                    daily_limit=int(item.get("daily_limit") or 30),
                    hourly_limit=int(item.get("hourly_limit") or 10),
                    min_reply_delay=float(item.get("min_reply_delay") or 3),
                    max_reply_delay=float(item.get("max_reply_delay") or 8),
                    handover_keywords=list(
                        item.get("handover_keywords") or ["人工", "投诉", "转人工"]
                    ),
                    require_mention=bool(item.get("require_mention", True)),
                )
            )
        values["targets"] = targets
        return cls(**values)

    def target_for(self, target_name: str = "", target_username: str = "") -> TargetConfig | None:
        for target in self.targets:
            if target_username and target.target_username == target_username:
                return target
            if target_name and target.target_name == target_name:
                return target
        return None
