"""本地风控：关键词拦截、频控、熔断、连续发送保护。"""
from __future__ import annotations

import time

BLOCK_KEYWORDS = [
    "操作频繁",
    "操作过于频繁",
    "账号存在安全风险",
    "当前设备",
    "不能加好友",
    "被限制",
    "被封",
    "封号",
    "系统检测",
    "异常",
    "限制登录",
    "安全风险",
    "无法登录",
]


class RiskGuard:
    def __init__(
        self,
        daily_limit: int = 300,
        hourly_limit: int = 60,
        minute_limit: int = 5,
        consecutive_limit: int = 12,
    ):
        self.daily_limit = daily_limit
        self.hourly_limit = hourly_limit
        self.minute_limit = minute_limit
        self.consecutive_limit = consecutive_limit
        self._sends: list[float] = []
        self._consecutive = 0
        self._blocked_until = 0.0

    def check_text(self, text: str):
        for keyword in BLOCK_KEYWORDS:
            if keyword in (text or ""):
                return False, keyword
        return True, ""

    def check_send(self) -> tuple:
        now = time.time()
        self._sends = [t for t in self._sends if t > now - 86400]
        if len(self._sends) >= self.daily_limit:
            return False, f"今日发送已达上限 {self.daily_limit}"
        hourly = [t for t in self._sends if t > now - 3600]
        if len(hourly) >= self.hourly_limit:
            return False, f"每小时发送已达上限 {self.hourly_limit}"
        minute = [t for t in self._sends if t > now - 60]
        if len(minute) >= self.minute_limit:
            return False, f"每分钟发送已达上限 {self.minute_limit}"
        if self._consecutive >= self.consecutive_limit:
            return False, f"连续发送已达上限 {self.consecutive_limit}"
        self._sends.append(now)
        self._consecutive += 1
        return True, ""

    def record_success(self):
        self._consecutive = 0

    def circuit_break(self, message: str) -> bool:
        text = message or ""
        if any(k in text for k in ("风控", "封号", "受限", "限制登录", "安全风险", "异常")):
            self._blocked_until = time.time() + 1800
            return True
        return time.time() < self._blocked_until

    def blocked_until_text(self) -> str:
        if time.time() < self._blocked_until:
            return "本地熔断中，等待人工处理"
        return ""
