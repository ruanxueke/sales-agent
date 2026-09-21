"""视觉受管执行器桌面客户端配置。"""
from __future__ import annotations

import os
import socket

INSTANCE_ID = os.environ.get("VISION_AGENT_INSTANCE_ID", "").strip() or f"agent-{socket.gethostname()}"
API_BASE = os.environ.get("VISION_AGENT_API_BASE", "http://127.0.0.1:5010").rstrip("/")
API_KEY = os.environ.get("API_KEYS", "") or os.environ.get("VISION_AGENT_API_KEY", "")
TOKEN = os.environ.get("VISION_AGENT_TOKEN", "")
MODE = os.environ.get("VISION_AGENT_MODE", "wecom").strip().lower()  # wecom / wechat
POLL_INTERVAL = max(1.0, float(os.environ.get("VISION_AGENT_POLL_INTERVAL", "3")))
SCREENSHOT_REGION = os.environ.get("VISION_AGENT_REGION", "")
MONITOR_TITLE = os.environ.get("VISION_AGENT_MONITOR", "")
MAX_SENDS_PER_DAY = int(os.environ.get("VISION_AGENT_MAX_SENDS_PER_DAY", "300"))
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen-vl-max")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
REPLY_MAX_LENGTH = int(os.environ.get("REPLY_MAX_LENGTH", "80"))
REPLY_MIN_DELAY = float(os.environ.get("VISION_REPLY_MIN_DELAY", "2.5"))
REPLY_MAX_DELAY = float(os.environ.get("VISION_REPLY_MAX_DELAY", "8.0"))
GROUP_TRIGGER_KEYWORDS = [
    k.strip()
    for k in os.environ.get("VISION_GROUP_TRIGGER_KEYWORDS", "你好,在吗,老师,客服,报价,课程,咨询").split(",")
    if k.strip()
]
IGNORE_CONTACTS = [k.strip() for k in os.environ.get("VISION_IGNORE_CONTACTS", "").split(",") if k.strip()]
MAX_CONSECUTIVE_SENDS = int(os.environ.get("VISION_MAX_CONSECUTIVE_SENDS", "12"))
DEBUG_NO_SEND = os.environ.get("VISION_DEBUG_NO_SEND", "").strip().lower() in ("1", "true", "yes")
DATA_DIR = os.environ.get(
    "VISION_AGENT_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vision_agent_data"),
)
