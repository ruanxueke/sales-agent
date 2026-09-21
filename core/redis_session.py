"""会话管理 - Redis 版（自动降级为内存模式）"""
from __future__ import annotations
import json
import logging
from collections import OrderedDict
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

# 内存降级存储
_fallback_store: dict[str, list[dict]] = {}
_fallback_cache: OrderedDict[str, str] = OrderedDict()


class SessionManager:
    """会话管理器（Redis 优先，无 Redis 则降级为内存）"""

    def __init__(self, redis=None):
        self._redis = redis
        if self._redis is None:
            self._try_connect_redis()

    def _try_connect_redis(self):
        try:
            from config.settings import settings
            if settings.REDIS_URL:
                from redis import Redis as SyncRedis
                self._redis = SyncRedis.from_url(settings.REDIS_URL, decode_responses=True)
                self._redis.ping()
                logger.info("Redis 连接成功")
                return
        except Exception as e:
            logger.debug("SessionManager._try_connect_redis 异常已忽略: %s", e)
        logger.info("Redis 未配置或不可用，使用内存模式")

    def save_context(self, session_id: str, input_text: str, output_text: str):
        entry = {"input": input_text, "output": output_text}
        if self._redis:
            key = f"session:{session_id}"
            self._redis.rpush(key, json.dumps(entry, ensure_ascii=False))
            try:
                from config.settings import settings
                self._redis.expire(key, settings.MEMORY_SESSION_TTL)
            except Exception:
                self._redis.expire(key, 3600)
            self._redis.ltrim(key, -50, -1)
        else:
            if session_id not in _fallback_store:
                _fallback_store[session_id] = []
            _fallback_store[session_id].append(entry)
            _fallback_store[session_id] = _fallback_store[session_id][-50:]

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        if self._redis:
            key = f"session:{session_id}"
            raw_list = self._redis.lrange(key, -limit, -1)
            history = []
            for raw in raw_list:
                try:
                    history.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
            return history
        else:
            records = _fallback_store.get(session_id, [])
            return records[-limit:]

    def get_history_text(self, session_id: str, limit: int = 10) -> str:
        history = self.get_history(session_id, limit)
        lines = []
        for h in history:
            lines.append(f"客户: {h.get('input', '')}")
            lines.append(f"客服: {h.get('output', '')}")
        return "\n".join(lines)

    def clear_session(self, session_id: str):
        if self._redis:
            self._redis.delete(f"session:{session_id}")
        else:
            _fallback_store.pop(session_id, None)

    @property
    def redis(self):
        """返回底层同步 Redis 客户端（未配置 Redis 时为 None）"""
        return self._redis

    def get_cache(self, key: str) -> Optional[str]:
        if self._redis:
            return self._redis.get(key)
        return _fallback_cache.get(key)

    def set_cache(self, key: str, value: str, ttl: int = 3600):
        if self._redis:
            self._redis.setex(key, ttl, value)
        else:
            _fallback_cache[key] = value
            _fallback_cache.move_to_end(key)
            max_entries = getattr(settings, "CACHE_MAX_ENTRIES", 1000)
            while len(_fallback_cache) > max_entries:
                _fallback_cache.popitem(last=False)

    def get_active_session_count(self) -> int:
        if self._redis:
            return len(self._redis.keys("session:*"))
        return len(_fallback_store)


session_manager = SessionManager()


def get_sync_redis():
    """获取当前会话管理器使用的同步 Redis 客户端（无 Redis 时为 None）"""
    return session_manager.redis


_cache_redis = None
_cache_redis_tried = False


def get_cache_redis():
    """获取「可淘汰缓存」专用 Redis 客户端。

    与 get_sync_redis() 分开的原因：锁 / 去重键 / 限流计数绝不能被 LRU 淘汰，
    而语义缓存可以。生产上应把 CACHE_REDIS_URL 指向独立实例或独立 DB。
    未配置 CACHE_REDIS_URL 时回退到主 Redis，行为与历史一致。
    """
    global _cache_redis, _cache_redis_tried
    if _cache_redis_tried:
        return _cache_redis
    _cache_redis_tried = True
    url = (getattr(settings, "CACHE_REDIS_URL", "") or "").strip()
    if not url:
        _cache_redis = session_manager.redis
        return _cache_redis
    try:
        from redis import Redis as SyncRedis
        client = SyncRedis.from_url(url, decode_responses=True)
        client.ping()
        _cache_redis = client
        logger.info("语义缓存 Redis 连接成功（独立实例）")
    except Exception as e:
        logger.warning("语义缓存 Redis 连接失败，回退主 Redis: %s", e)
        _cache_redis = session_manager.redis
    return _cache_redis


RedisSessionManager = SessionManager
