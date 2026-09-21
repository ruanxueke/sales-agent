"""语义缓存 — 减少重复 LLM 调用

实现要点（相对旧版的关键修正）：
1. 使用 get_cache_redis()（可指向独立实例），缓存键可以被 LRU 淘汰，
   而锁/去重/限流键不会被牵连；
2. 用有序集合 `sem_index` 维护「最近使用」索引，相似度只比对最近
   CACHE_SEARCH_LIMIT 条候选（默认 300），不再对全库做 SCAN；
3. 淘汰按索引里的最旧记录进行，不再用 `dbsize()` 判断容量，
   避免把同库其他业务键算进缓存容量导致「每次写入都触发全库扫描」。

原理：
1. 用户提问 → 生成向量
2. 在缓存候选中找最相似的问题
3. 相似度 > 阈值 → 直接返回缓存结果
4. 否则 → 调 LLM → 结果存入缓存
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
from typing import Optional

import numpy as np
from config.settings import settings
from core.redis_session import get_cache_redis, session_manager

logger = logging.getLogger(__name__)

INDEX_KEY = "sem_index"


class SemanticCache:
    def __init__(self):
        self._embeddings_func = None
        self._threshold = settings.CACHE_SIMILARITY_THRESHOLD
        self._ttl = settings.CACHE_TTL

    def _get_embedding(self, text: str) -> list[float]:
        """生成文本向量（延迟导入 embedding 模型）"""
        if self._embeddings_func is None:
            from core.llm import create_embeddings
            emb = create_embeddings()
            self._embeddings_func = emb.embed_query
        return self._embeddings_func(text)

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        a_np = np.array(a, dtype=np.float32)
        b_np = np.array(b, dtype=np.float32)
        if np.linalg.norm(a_np) == 0 or np.linalg.norm(b_np) == 0:
            return 0.0
        return float(np.dot(a_np, b_np) / (np.linalg.norm(a_np) * np.linalg.norm(b_np)))

    def _cache_key(self, text: str) -> str:
        """确定性缓存 Key（用于精确匹配）"""
        return f"sem_cache:{hashlib.md5(text.encode()).hexdigest()}"

    def _meta_key(self, text: str) -> str:
        return f"sem_meta:{hashlib.md5(text.encode()).hexdigest()}"

    def _redis(self):
        return get_cache_redis()

    def get(self, query: str) -> Optional[str]:
        """获取缓存结果"""
        if not settings.CACHE_ENABLED:
            return None

        redis = self._redis()

        # 1. 精确命中
        exact = session_manager.get_cache(self._cache_key(query))
        if exact is not None:
            logger.debug("语义缓存精确命中: %s...", query[:30])
            return exact

        if redis is None:
            return None

        # 2. 取最近使用的候选做向量检索（不再全库 SCAN）
        try:
            limit = max(1, int(getattr(settings, "CACHE_SEARCH_LIMIT", 300) or 300))
            candidates = redis.zrevrange(INDEX_KEY, 0, limit - 1)
        except Exception as e:
            logger.warning("读取语义缓存索引失败: %s", e)
            return None
        if not candidates:
            logger.debug("语义缓存未命中（索引为空）: %s...", query[:30])
            return None

        try:
            query_vec = self._get_embedding(query)
        except Exception as e:
            logger.warning("生成向量失败: %s", e)
            return None

        try:
            raw_list = redis.mget(candidates)
        except Exception as e:
            logger.warning("批量读取语义缓存元数据失败: %s", e)
            return None

        best_match = None
        best_score = 0.0
        best_meta_key = None
        for meta_key, raw in zip(candidates, raw_list):
            if not raw:
                continue
            try:
                meta = json.loads(raw)
            except json.JSONDecodeError:
                continue
            score = self._cosine_similarity(query_vec, meta.get("vector", []))
            if score > best_score:
                best_score = score
                best_match = meta.get("result_key")
                best_meta_key = meta_key

        if best_match and best_score >= self._threshold:
            result = redis.get(best_match)
            if result:
                # 命中即刷新为「最近使用」，降低被淘汰的概率
                try:
                    redis.zadd(INDEX_KEY, {best_meta_key: time.time()})
                except Exception as e:
                    logger.debug("SemanticCache.get 异常已忽略: %s", e)
                logger.info("语义缓存相似命中 (score=%.3f): %s...", best_score, query[:30])
                return result

        logger.debug("语义缓存未命中: %s...", query[:30])
        return None

    def set(self, query: str, result: str):
        """存入缓存"""
        if not settings.CACHE_ENABLED:
            return

        redis = self._redis()
        if redis is None:
            session_manager.set_cache(self._cache_key(query), result, self._ttl)
            return

        try:
            query_vec = self._get_embedding(query)
        except Exception as e:
            logger.warning("缓存：生成向量失败: %s", e)
            return

        # 存储结果
        result_key = self._cache_key(query)
        session_manager.set_cache(result_key, result, self._ttl)

        # 存储元数据（向量 + 结果指针）+ 写入索引
        meta_key = self._meta_key(query)
        meta = {
            "query": query,
            "vector": query_vec,
            "result_key": result_key,
            "timestamp": time.time(),
        }
        try:
            pipe = redis.pipeline()
            pipe.setex(meta_key, self._ttl, json.dumps(meta, ensure_ascii=False))
            pipe.zadd(INDEX_KEY, {meta_key: meta["timestamp"]})
            pipe.execute()
        except Exception as e:
            logger.warning("写入语义缓存失败: %s", e)
            return

        self._evict_oldest()

    def _evict_oldest(self):
        """按索引中的最旧记录淘汰，避免全库扫描"""
        redis = self._redis()
        if redis is None:
            return
        try:
            max_entries = max(1, int(getattr(settings, "CACHE_MAX_ENTRIES", 20000) or 20000))
            total = int(redis.zcard(INDEX_KEY) or 0)
            if total <= max_entries:
                return
            evict_count = min(500, total - max_entries)
            stale = redis.zrange(INDEX_KEY, 0, evict_count - 1)
            if not stale:
                return
            pipe = redis.pipeline()
            for meta_key in stale:
                raw = redis.get(meta_key)
                if raw:
                    try:
                        result_key = json.loads(raw).get("result_key")
                        if result_key:
                            pipe.delete(result_key)
                    except json.JSONDecodeError as e:
                        logger.debug("SemanticCache._evict_oldest 异常已忽略: %s", e)
                pipe.delete(meta_key)
                pipe.zrem(INDEX_KEY, meta_key)
            pipe.execute()
        except Exception as e:
            logger.warning("缓存淘汰出错: %s", e)

    def clear(self):
        """清空缓存"""
        redis = self._redis()
        if redis is None:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = redis.scan(cursor=cursor, match="sem_meta:*", count=500)
                pipe = redis.pipeline()
                for key in keys:
                    meta_raw = redis.get(key)
                    if meta_raw:
                        try:
                            rk = json.loads(meta_raw).get("result_key")
                            if rk:
                                pipe.delete(rk)
                        except json.JSONDecodeError as e:
                            logger.debug("SemanticCache.clear 异常已忽略: %s", e)
                    pipe.delete(key)
                if keys:
                    pipe.execute()
                if cursor == 0:
                    break
            redis.delete(INDEX_KEY)
        except Exception as e:
            logger.warning("清空语义缓存出错: %s", e)


semantic_cache = SemanticCache()
