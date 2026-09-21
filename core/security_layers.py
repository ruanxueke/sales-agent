"""安全合规层：提示词注入防护、敏感信息脱敏、输出审核、滥用黑名单"""
from __future__ import annotations
import re
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime
from pathlib import Path

from config.settings import settings

DB_PATH = Path(settings.DATA_DIR) / "customers.db"

INJECTION_WORDS = [
    "忽略以上", "忽略指令", "忽略规则", "无视提示词", "不要遵守", "系统提示",
    "system prompt", "你是AI", "你不是销售", "请扮演", "解除限制", "忘记你是",
]

BANNED_REPLY_WORDS = [
    "百分之百", "百分百", "保证赚钱", "包赚", "稳赚", "绝对有效",
    "绝对能", "一定赚", "保证收益",
]

_ID_CARD_RE = re.compile(r"\d{17}[\dXx]|\d{15}")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_BANK_RE = re.compile(r"\d{16,19}")

_mask_lock = threading.Lock()


class SecurityLayers:
    @staticmethod
    def detect_injection(message: str) -> bool:
        text = (message or "").lower()
        return any(word.lower() in text for word in INJECTION_WORDS)

    @staticmethod
    def mask_sensitive(text: str) -> str:
        """存储级脱敏：整段打码"""
        value = text or ""
        value = _ID_CARD_RE.sub("***********", value)
        value = _PHONE_RE.sub("***********", value)
        value = _BANK_RE.sub("****************", value)
        return value

    @staticmethod
    def mask_display(text: str) -> str:
        """展示级脱敏：手机号 138****1234，身份证留首尾"""
        value = text or ""
        def _phone(m):
            s = m.group(0)
            return s[:3] + "****" + s[-4:] if len(s) >= 11 else s
        def _idcard(m):
            s = m.group(0)
            return s[:6] + "********" + s[-4:] if len(s) >= 15 else s
        value = _ID_CARD_RE.sub(_idcard, value)
        value = _PHONE_RE.sub(_phone, value)
        return _BANK_RE.sub("****************", value)

    @staticmethod
    def mask_export(text: str) -> str:
        """导出级脱敏：除首尾外全部打码，银行卡/手机/身份证全码"""
        return SecurityLayers.mask_sensitive(text)

    @staticmethod
    def moderate_reply(reply: str) -> str | None:
        """命中绝对承诺词时返回安全兜底文案"""
        if any(word in (reply or "") for word in BANNED_REPLY_WORDS):
            return "这个我没办法给您打包票，只能说课程内容按实际交付，效果因人而异。您可以先了解课程内容再决定。"
        return None


class BlocklistManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS blocked_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    created_at TEXT
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def is_blocked(self, session_id: str) -> bool:
        if not session_id:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM blocked_users WHERE session_id = ? LIMIT 1", (session_id,)
            ).fetchone()
        return row is not None

    def add(self, session_id: str, reason: str = "") -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO blocked_users (session_id, reason, created_at) VALUES (?, ?, ?)",
                (session_id, reason, self._now()),
            )
            self._conn.commit()
            return {"id": cur.lastrowid, "session_id": session_id, "reason": reason}

    def remove(self, session_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM blocked_users WHERE session_id = ?", (session_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM blocked_users ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


security_layers = SecurityLayers()
blocklist_manager = BlocklistManager()
