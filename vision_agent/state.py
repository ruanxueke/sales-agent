"""本地状态：消息指纹去重、人工接管标记、冷却时间。"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from . import config

logger = logging.getLogger(__name__)


class LocalState:
    def __init__(self):
        self._lock = threading.RLock()
        os.makedirs(config.DATA_DIR, exist_ok=True)
        self.path = os.path.join(config.DATA_DIR, f"state_{config.INSTANCE_ID}.json")
        self._seen: set[str] = set()
        self._human: dict[str, float] = {}
        self._cooldown: dict[str, float] = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                data = json.loads(open(self.path, encoding="utf-8").read())
                self._seen = set(data.get("seen") or [])
                self._human = data.get("human") or {}
                self._cooldown = data.get("cooldown") or {}
        except Exception as e:
            logger.warning("本地状态读取失败: %s", e)

    def _save(self):
        try:
            data = {
                "seen": sorted(self._seen)[-50000:],
                "human": self._human,
                "cooldown": self._cooldown,
            }
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("本地状态写入失败: %s", e)

    def seen_local(self, fingerprint: str) -> bool:
        with self._lock:
            return fingerprint in self._seen

    def remember(self, fingerprint: str):
        with self._lock:
            self._seen.add(fingerprint)
            if len(self._seen) > 50000:
                self._seen = set(sorted(self._seen)[-50000:])
            self._save()

    def set_human(self, contact: str, active: bool = True):
        with self._lock:
            key = self._key(contact)
            if active:
                self._human[key] = time.time()
            else:
                self._human.pop(key, None)
            self._save()

    def is_human(self, contact: str) -> bool:
        with self._lock:
            return self._key(contact) in self._human

    def set_cooldown(self, contact: str, seconds: int = 60):
        with self._lock:
            self._cooldown[self._key(contact)] = time.time() + seconds
            self._save()

    def in_cooldown(self, contact: str) -> bool:
        with self._lock:
            return time.time() < self._cooldown.get(self._key(contact), 0)

    def _key(self, contact: str) -> str:
        return f"{config.INSTANCE_ID}::{contact}"
