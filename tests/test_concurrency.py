"""并发架构测试 — 验证限流、会话、缓存、队列等核心模块"""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# 确保能找到项目模块
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fakeredis

# ==================== 配置 fakeredis 全局注入 ====================
import config.settings
from core import redis_session, concurrency, cache
from core.redis_session import RedisSessionManager

# 创建 fakeredis 实例（不连真实 Redis）
fake_redis = fakeredis.FakeRedis(decode_responses=True)
fake_async_redis = fakeredis.FakeRedis(decode_responses=True)

# 全局替换：让所有模块用 fake redis
redis_session.session_manager = RedisSessionManager(redis=fake_redis)
concurrency.rate_limiter = concurrency.RateLimiter(redis=fake_redis)

# 语义缓存也用 fake redis
cache.session_manager = redis_session.session_manager
cache.semantic_cache = cache.SemanticCache()


# ==================== 测试1：限流器 ====================

def test_rate_limiter():
    rl = concurrency.RateLimiter(redis=fakeredis.FakeRedis(decode_responses=True))
    user = "test_user_001"

    # 正常请求应该通过
    results = []
    for i in range(5):
        ok = rl.check_user(user)
        results.append(ok)

    passed = all(results)
    print(f"  正常请求(5次)全部通过: {'[OK]' if passed else '[FAIL]'}")
    assert passed, "前5次请求应全部通过"

    # 模拟大量请求触发限流
    for _ in range(20):
        rl.check(user, limit=5, window=1)

    remaining = rl.remaining(user, limit=5, window=1)
    wait = rl.wait_time(user, limit=5, window=1)
    print(f"  触发限流后剩余次数: {remaining}, 需要等待: {wait:.2f}s")
    assert remaining == 0, "应触发限流，剩余次数为0"
    assert wait > 0, "应需要等待"
    print(f"  限流触发: [OK]")


# ==================== 测试2：API Key 轮转 ====================

def test_api_key_rotator():
    import config.settings as cfg
    cfg.settings.DEEPSEEK_API_KEYS = [
        "sk-key-a-xxxx", "sk-key-b-xxxx", "sk-key-c-xxxx"
    ]
    rotator = concurrency.APIKeyRotator()
    keys = set()

    for _ in range(6):
        k = rotator.get_key()
        keys.add(k)

    assert len(keys) == 3, "应轮转出3个不同的 Key"
    print(f"  可用 Key 数: {len(keys)} [OK]")

    first_key = rotator.current_key
    rotator.mark_failure(first_key, cooldown=10)
    second_key = rotator.get_key()
    assert second_key != first_key, "失败后应切换到不同 Key"
    print(f"  Key 故障切换: {first_key[:8]}... -> {second_key[:8]}... [OK]")


# ==================== 测试3：Redis 会话并发读写 ====================

def test_concurrent_sessions():
    sm = RedisSessionManager(redis=fakeredis.FakeRedis(decode_responses=True))
    num_users = 50
    rounds_per_user = 5

    def simulate_user(user_id: int):
        session_id = f"user_{user_id:04d}"
        for r in range(rounds_per_user):
            sm.save_context(
                session_id,
                f"用户{user_id}的第{r+1}条消息",
                f"回复给用户{user_id}的第{r+1}条消息",
            )
        history = sm.get_history(session_id, limit=10)
        return len(history)

    start = time.time()
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(simulate_user, i) for i in range(num_users)]
        results = [f.result() for f in as_completed(futures)]

    elapsed = time.time() - start
    total_msgs = sum(results)
    print(f"  {num_users}用户 x {rounds_per_user}轮 = 共{num_users * rounds_per_user}条消息")
    print(f"  耗时: {elapsed:.3f}s, 平均: {num_users/elapsed:.1f} 用户/秒")
    assert all(r == rounds_per_user for r in results), "所有用户消息数应完整"
    print(f"  全部成功: [OK]")

    active = sm.get_active_session_count()
    print(f"  活跃会话数: {active}")
    assert active == num_users, f"应有 {num_users} 个活跃会话"
    print(f"  会话计数准确: [OK]")


# ==================== 测试4：语义缓存并发 ====================

def test_semantic_cache():
    sc = cache.SemanticCache()

    def fake_embedding(text: str):
        return [
            int(hashlib.md5(f"{text}:{i}".encode()).hexdigest()[:4], 16) % 1000 / 1000.0
            for i in range(384)
        ]

    sc._get_embedding = fake_embedding

    sc.set("这个产品多少钱", "售价是 299 元")
    sc.set("你们有什么产品", "我们有 A、B、C 三款产品")

    result = sc.get("这个产品多少钱")
    assert result == "售价是 299 元", "精确缓存应命中"
    print(f"  精确命中: [OK]")

    result2 = sc.get("完全不相关的内容")
    assert result2 is None, "不相关内容应未命中"
    print(f"  不相关不命中: [OK]")

    def concurrent_write(idx: int):
        sc.set(f"并发问题{idx}", f"并发答案{idx}")

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(concurrent_write, i) for i in range(20)]
        for f in as_completed(futures):
            f.result()

    print(f"  20路并发写入: [OK]")

    # 并发写入后必须能读回，否则"写入成功"只是假象。
    assert sc.get("并发问题7") == "并发答案7", "并发写入的条目应可读回"


# ==================== 测试5：Agent 限流 + 缓存集成 ====================

def test_agent_concurrency():
    import time

    def mock_agent_chat(message: str, session_id: str) -> str:
        rl = concurrency.RateLimiter(redis=fakeredis.FakeRedis(decode_responses=True))
        if not rl.check_user(session_id):
            return "TOO_FAST"
        time.sleep(0.05)
        return f"回复: {message}"

    results = {}
    lock = threading.Lock()

    def user_chat(user_id: int, message: str):
        session_id = f"sim_user_{user_id}"
        reply = mock_agent_chat(message, session_id)
        with lock:
            results.setdefault(session_id, []).append(reply)

    start = time.time()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = []
        for u in range(3):
            for _ in range(5):
                futures.append(pool.submit(user_chat, u, f"问题来自用户{u}"))

        for f in as_completed(futures):
            f.result()

    elapsed = time.time() - start
    total = sum(len(v) for v in results.values())
    serial_time = 3 * 5 * 0.05
    print(f"  3用户 x 5请求 = {total} 次调用")
    print(f"  总耗时: {elapsed:.3f}s（串行需 {serial_time:.2f}s）")
    speedup = serial_time / elapsed
    print(f"  加速比: {speedup:.1f}x")

    too_fast_count = sum(
        1 for replies in results.values() for r in replies if r == "TOO_FAST"
    )
    print(f"  被限流次数: {too_fast_count}")
    print(f"  并发处理: {'' if speedup > 1.5 else '预警'}")

    # 这里必须断言。之前只打印不断言，一旦并发丢回复测试依然判定通过，
    # 等于给并发链路发一张假绿灯。
    assert total == 15, f"3用户 x 5请求 应产生 15 条回复，实际 {total}"
    assert len(results) == 3, f"应覆盖 3 个会话，实际 {len(results)}"
    assert all(len(v) == 5 for v in results.values()), (
        f"每个用户的回复数应完整: { {k: len(v) for k, v in results.items()} }"
    )


# ==================== 测试6：FastAPI 并发请求 ====================

def test_fastapi_concurrent():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    test_app = FastAPI()
    from core.concurrency import rate_limiter as rl
    import time

    @test_app.post("/api/chat/sync")
    async def chat_sync(message: str = "你好", session_id: str = "test"):
        if not rl.check_user(session_id):
            return {"error": "rate_limited"}
        time.sleep(0.02)
        return {"reply": f"回复: {message}", "session_id": session_id}

    client = TestClient(test_app)

    start = time.time()
    results = []

    def send_request(i: int):
        resp = client.post(
            "/api/chat/sync",
            json={"message": f"并发查询{i}", "session_id": f"stress_user_{i % 3}"},
        )
        return resp.json()

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(send_request, i) for i in range(10)]
        for f in as_completed(futures):
            r = f.result()
            results.append(r)

    elapsed = time.time() - start
    success = [r for r in results if "reply" in r]
    limited = [r for r in results if "error" in r]

    serial_time = 10 * 0.02
    speedup = serial_time / elapsed
    print(f"  10并发请求: 成功{len(success)} 限流{len(limited)}")
    print(f"  总耗时: {elapsed:.3f}s（串行需 {serial_time:.2f}s）")
    print(f"  加速比: {speedup:.1f}x")
    assert len(success) > 0, "至少有一些请求应成功"
    assert len(success) + len(limited) == 10, "10 个请求都应返回结果，不能丢包"
    print(f"  FastAPI 并发处理: {'' if speedup > 2 else '预警'}")


# ==================== 总结 ====================


if __name__ == "__main__":
    print("=" * 60)

    print("销售客服智能体 - 并发架构测试")

    print("=" * 60)

    print("\n--- 测试1: 限流器 ---")

    test_rate_limiter()

    print("\n--- 测试2: API Key 轮转 ---")

    test_api_key_rotator()

    print("\n--- 测试3: 会话并发读写 ---")

    test_concurrent_sessions()

    print("\n--- 测试4: 语义缓存 ---")

    test_semantic_cache()

    print("\n--- 测试5: Agent 并发调用模拟 ---")

    test_agent_concurrency()

    print("\n--- 测试6: FastAPI 并发请求 ---")

    test_fastapi_concurrent()

    print("\n" + "=" * 60)

    print("所有并发测试完成!")

    print("=" * 60)

    print("测试覆盖:")

    print("  - 限流器（滑动窗口）")

    print("  - API Key 轮转 + 故障切换")

    print("  - 50用户 Redis 会话并发读写")

    print("  - 语义缓存读写 + 并发写入")

    print("  - Agent 调用全链路（含限流）")

    print("  - FastAPI 接口并发请求")

    print("=" * 60)
