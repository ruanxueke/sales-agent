"""登录失败计数与锁定：优先 Redis（多 worker 共享），Redis 不可用时退回进程内存。

原实现把失败计数放在 `EnterpriseManager._login_failures` 这个**进程内字典**里：
  * uvicorn 起 2 个 worker 时，攻击者交替打请求即可让每个 worker 各自只记 2 次，
    "5 次失败锁 15 分钟"形同虚设；
  * 进程重启（每次发布都会）直接清零，之前撞了多少次全部作废。

所以计数必须落到所有 worker 都能看到的地方。Redis 是天然选择；拿不到 Redis 时
退回内存字典，但要带上限，避免用随机用户名把内存打爆。
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)

MAX_FAILURES = 5          # 同一标识符在窗口内允许的失败次数
FAIL_WINDOW = 900         # 计数窗口（秒）
LOCK_SECONDS = 900        # 触发后的锁定时长（秒）
# IP 维度放宽一些：同一个出口 IP 后面可能坐着整个办公室。
IP_MAX_FAILURES = 20
# 自助注册是未鉴权接口，按 IP 限流，避免被刷出成百上千个租户。
REGISTER_MAX_PER_WINDOW = 10
REGISTER_WINDOW = 3600
# 内存兜底字典的容量上限（超出后淘汰最旧的条目）。
MEMORY_CAPACITY = 10_000

_memory: "OrderedDict[str, list]" = OrderedDict()


def _redis():
    """取同步 Redis 客户端；未配置/不可用时返回 None（只记一次日志）。"""
    try:
        from core.redis_session import get_sync_redis

        return get_sync_redis()
    except Exception as e:  # pragma: no cover - 取决于部署环境
        logger.debug("登录锁定未接入 Redis: %s", e)
        return None


def _key(identifier: str) -> str:
    return f"login:fail:{identifier}"


def _lock_key(identifier: str) -> str:
    return f"login:lock:{identifier}"


def _norm(identifier: str) -> str:
    return (identifier or "").strip().lower() or "unknown"


def locked_seconds(identifier: str) -> int:
    """返回剩余锁定秒数；0 表示未锁定。

    注意：`until == 0` 表示"记过失败但还没到阈值"，**不能**当成过期条目删掉，
    否则每读一次状态就把失败计数清零，5 次锁定永远不会触发。
    """
    ident = _norm(identifier)
    r = _redis()
    if r is not None:
        try:
            ttl = r.ttl(_lock_key(ident))
            return int(ttl) if ttl and ttl > 0 else 0
        except Exception as e:
            logger.debug("读取登录锁定状态失败，回退内存: %s", e)

    entry = _memory.get(ident)
    if not entry:
        return 0
    now = time.time()
    count, until, last_fail = entry[0], entry[1], entry[2]
    if until and until > now:
        return int(until - now)
    # 锁定已到期（或本轮还没触发锁定）：只清掉"锁定"标记，保留窗口内的失败计数。
    if until:
        entry[1] = 0.0
    if now - last_fail > FAIL_WINDOW:
        _memory.pop(ident, None)
    return 0


def hit(identifier: str, *, limit: int, window: int) -> tuple[int, bool]:
    """通用窗口计数限流：返回 (窗口内累计次数, 是否放行)。

    与 fail 计数分开是因为语义不同——这里没有"锁定"的概念，只是单纯数次数。
    """
    ident = _norm(identifier)
    r = _redis()
    if r is not None:
        try:
            k = f"rate:{ident}"
            pipe = r.pipeline()
            pipe.incr(k)
            pipe.expire(k, window)
            count = int(pipe.execute()[0])
            return count, count <= limit
        except Exception as e:
            logger.warning("限流计数写入 Redis 失败，回退内存: %s", e)

    key = f"rate:{ident}"
    now = time.time()
    entry = _memory.get(key)
    if entry and now - entry[2] <= window:
        count = entry[0] + 1
    else:
        count = 1
    _memory[key] = [count, 0.0, now]
    _memory.move_to_end(key)
    while len(_memory) > MEMORY_CAPACITY:
        _memory.popitem(last=False)
    return count, count <= limit


def record_failure(
    identifier: str,
    *,
    limit: int = MAX_FAILURES,
    window: int = FAIL_WINDOW,
    lock_seconds: int = LOCK_SECONDS,
) -> tuple[int, int]:
    """记一次失败；返回 (窗口内失败次数, 本次触发的锁定秒数)。

    第二项为 0 表示这次还没触发锁定。
    """
    ident = _norm(identifier)
    r = _redis()
    if r is not None:
        try:
            k = _key(ident)
            pipe = r.pipeline()
            pipe.incr(k)
            pipe.expire(k, window)
            count = int(pipe.execute()[0])
            if count >= limit:
                r.set(_lock_key(ident), "1", ex=lock_seconds)
                # 计数清零，锁定解除后重新开始累计。
                r.delete(k)
                return count, lock_seconds
            return count, 0
        except Exception as e:
            logger.warning("登录失败计数写入 Redis 失败，回退内存: %s", e)

    now = time.time()
    entry = _memory.get(ident)
    if entry and now - entry[2] <= window:
        count = entry[0] + 1
    else:
        count = 1
    if count >= limit:
        # 与 Redis 分支保持一致：触发锁定时把计数清零，只留下锁定标记。
        _memory[ident] = [0, now + lock_seconds, now]
        _memory.move_to_end(ident)
        return count, lock_seconds
    _memory[ident] = [count, 0.0, now]
    _memory.move_to_end(ident)
    while len(_memory) > MEMORY_CAPACITY:
        _memory.popitem(last=False)
    return count, 0


def clear(identifier: str) -> None:
    """登录成功后清空计数与锁定。"""
    ident = _norm(identifier)
    r = _redis()
    if r is not None:
        try:
            r.delete(_key(ident), _lock_key(ident))
            return
        except Exception as e:
            logger.debug("清除登录失败计数失败，回退内存: %s", e)
    _memory.pop(ident, None)


def reset_local_state() -> None:
    """仅供测试：清空内存兜底状态。"""
    _memory.clear()
