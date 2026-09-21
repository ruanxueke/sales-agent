"""并发控制 - 限流器 + API Key 轮转"""
from __future__ import annotations
import logging
import time
from collections import OrderedDict

from config.settings import settings
from core.redis_session import get_sync_redis

logger = logging.getLogger(__name__)


class RateLimiter:
    """滑动窗口限流器"""
    def __init__(self, redis=None, max_ids: int = None):
        self.redis = redis or get_sync_redis()
        self._memory: OrderedDict[str, list[float]] = OrderedDict()
        self._max_ids = max_ids or settings.RATE_LIMIT_MEMORY_MAX_IDS

    def _touch(self, key: str):
        if key in self._memory:
            self._memory.move_to_end(key)
        while len(self._memory) > self._max_ids:
            self._memory.popitem(last=False)

    def check(self, identifier, limit, window=1):
        key = f"ratelimit:user:{identifier}"
        now = time.time()
        if self.redis is None:
            recent = [t for t in self._memory.get(key, []) if t > now - window]
            recent.append(now)
            self._memory[key] = recent
            self._touch(key)
            return len(recent) <= limit
        p = self.redis.pipeline()
        p.zadd(key, {str(now): now})
        p.zremrangebyscore(key, 0, now - window)
        p.zcard(key)
        p.expire(key, window + 1)
        return p.execute()[2] <= limit

    def check_user(self, uid):
        return self.check(uid, settings.RATE_LIMIT_PER_USER, settings.RATE_LIMIT_WINDOW)

    def check_global(self):
        return self.check("global", settings.RATE_LIMIT_GLOBAL, settings.RATE_LIMIT_WINDOW)

    def remaining(self, identifier, limit, window=1):
        key = f"ratelimit:user:{identifier}"
        now = time.time()
        if self.redis is None:
            recent = [t for t in self._memory.get(key, []) if t > now - window]
            if recent:
                self._memory[key] = recent
                self._touch(key)
            elif key in self._memory:
                self._memory.pop(key)
            return max(0, limit - len(recent))
        self.redis.zremrangebyscore(key, 0, now - window)
        return max(0, limit - self.redis.zcard(key))

    def wait_time(self, identifier, limit, window=1):
        key = f"ratelimit:user:{identifier}"
        now = time.time()
        if self.redis is None:
            recent = [t for t in self._memory.get(key, []) if t > now - window]
            if recent:
                self._memory[key] = recent
                self._touch(key)
            elif key in self._memory:
                self._memory.pop(key)
            if len(recent) < limit:
                return 0.0
            return max(0.0, recent[0] + window - now)
        self.redis.zremrangebyscore(key, 0, now - window)
        if self.redis.zcard(key) < limit: return 0.0
        oldest = self.redis.zrange(key, 0, 0, withscores=True)
        return max(0.0, oldest[0][1] + window - now) if oldest else 0.0


class APIKeyRotator:
    """API Key 轮转器 - 轮询分配 + 故障自动切换"""
    def __init__(self):
        self.keys = list(settings.DEEPSEEK_API_KEYS)
        if not self.keys: raise ValueError("no keys")
        self._cur = 0
        self._fails = {}

    @property
    def current_key(self):
        return self.keys[self._cur]

    def get_key(self):
        now = time.time()
        self._fails = {k: v for k, v in self._fails.items() if v > now}
        for _ in range(len(self.keys)):
            self._cur = (self._cur + 1) % len(self.keys)
            key = self.keys[self._cur]
            if key not in self._fails: return key
        logger.warning("all keys in cooldown")
        return self.keys[0]

    def mark_failure(self, key, cooldown=60):
        self._fails[key] = time.time() + cooldown
        logger.warning(f"key {key[:8]}... cooldown {cooldown}s")

    def mark_success(self, key):
        self._fails.pop(key, None)

    def rotate(self):
        self._cur = (self._cur + 1) % len(self.keys)


rate_limiter = RateLimiter()
try:
    api_key_rotator = APIKeyRotator()
except ValueError:
    logger.warning("API Key rotator unavailable")
    api_key_rotator = None
