"""LLM 路由的运行态：连续失败计数 / 临时降级截止时间 / 手动指定模型。

原实现把这三个值放在 `LLMRouter` 实例（模块级单例）里，本质是**进程内状态**：

* api 容器起多个 uvicorn worker 时，worker A 判定"主模型连续失败"并降级 5 分钟，
  worker B 完全不知道，同一个客户的相邻两轮对话可能一轮走主模型、一轮走备用；
* `POST /api/v1/system/llm/switch` 只改了接住这个请求的那个 worker，其余 worker
  照旧用主模型——运维点了"切到备用"，日志上看起来生效，实际只生效了 1/N；
* 每次发布重启进程，累计的连续失败次数与手动指定一起丢光。

所以状态必须外置。优先 Redis（所有 worker 共享同一份）；拿不到 Redis 时退回进程内存，
让单机 / 单进程部署下的行为与历史保持一致。

与 `core/login_guard.py` 的差别：这里的键是**固定几个**，不随外部输入增长，所以内存
兜底不需要容量上限（登录失败计数会被随机用户名打爆，这里不会）。
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# 连续失败多少次触发临时降级
FAILURE_THRESHOLD = 3
# 临时降级持续时长（秒）
FAILOVER_SECONDS = 300
# 连续失败计数的存续时长：超过这么久没有新的失败，就不再算"连续"。
# 原实现没有这个时间维度，昨天半夜攒下的 2 次失败会让今天第一次失败直接触发降级。
FAILURE_TTL = 600

_K_STREAK = "llm:fail:streak"
_K_FAILOVER = "llm:failover:until"
_K_FORCE = "llm:force"

ALLOWED_FORCE = ("", "primary", "backup")

_memory = {"streak": 0, "streak_at": 0.0, "failover_until": 0.0, "force": ""}


def _redis():
    """取同步 Redis 客户端；未配置 / 不可用时返回 None。"""
    try:
        from core.redis_session import get_sync_redis

        return get_sync_redis()
    except Exception as e:  # pragma: no cover - 取决于部署环境
        logger.debug("LLM 路由状态未接入 Redis: %s", e)
        return None


def backend_name() -> str:
    """当前状态存在哪：`redis`（多 worker 共享）或 `memory`（仅本进程）。

    暴露给状态接口，是为了让"我点了切备用，为什么另一个请求还在用主模型"
    这类问题能一眼定位，而不是靠猜。
    """
    return "redis" if _redis() is not None else "memory"


# ---------------------------------------------------------------- 连续失败计数


def record_failure() -> int:
    """记一次主模型调用失败，返回当前连续失败次数（跨 worker 累计）。"""
    now = time.time()
    r = _redis()
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incr(_K_STREAK)
            pipe.expire(_K_STREAK, FAILURE_TTL)
            return int(pipe.execute()[0])
        except Exception as e:
            logger.warning("LLM 失败计数写入 Redis 失败，回退内存: %s", e)

    if now - _memory["streak_at"] > FAILURE_TTL:
        _memory["streak"] = 0
    _memory["streak"] += 1
    _memory["streak_at"] = now
    return _memory["streak"]


def failure_streak() -> int:
    """当前连续失败次数（只读，不清零）。"""
    now = time.time()
    r = _redis()
    if r is not None:
        try:
            raw = r.get(_K_STREAK)
            return int(raw) if raw else 0
        except Exception as e:
            logger.debug("读取 LLM 失败计数失败，回退内存: %s", e)

    if now - _memory["streak_at"] > FAILURE_TTL:
        return 0
    return int(_memory["streak"])


def record_success() -> None:
    """主模型成功一次：清零连续失败计数。

    不动「手动指定」，也不提前解除已经生效的临时降级——降级由 `start_failover()`
    写入 TTL 自行到期，这样多 worker 之间不会互相踩。
    """
    _memory["streak"] = 0
    _memory["streak_at"] = time.time()
    r = _redis()
    if r is None:
        return
    try:
        r.delete(_K_STREAK)
    except Exception as e:
        logger.debug("清除 LLM 失败计数失败: %s", e)


def reset_failure() -> None:
    """别名，语义更直白：仅清连续失败计数。"""
    record_success()


# ---------------------------------------------------------------- 临时降级窗口


def start_failover(seconds: int = FAILOVER_SECONDS) -> None:
    """开始 / 续期临时降级窗口。"""
    now = time.time()
    seconds = max(1, int(seconds))
    _memory["failover_until"] = now + seconds
    r = _redis()
    if r is None:
        return
    try:
        r.set(_K_FAILOVER, f"{now + seconds:.3f}", ex=seconds)
    except Exception as e:
        logger.warning("写入 LLM 降级窗口失败，回退内存: %s", e)


def failover_remaining() -> int:
    """临时降级剩余秒数；0 表示不在降级窗口内。"""
    now = time.time()
    r = _redis()
    if r is not None:
        try:
            raw = r.get(_K_FAILOVER)
            if not raw:
                return 0
            return max(0, int(float(raw) - now))
        except Exception as e:
            logger.debug("读取 LLM 降级窗口失败，回退内存: %s", e)

    remaining = _memory["failover_until"] - now
    return max(0, int(remaining)) if remaining > 0 else 0


def clear_failover() -> None:
    """手动解除临时降级窗口。"""
    _memory["failover_until"] = 0.0
    r = _redis()
    if r is None:
        return
    try:
        r.delete(_K_FAILOVER)
    except Exception as e:
        logger.debug("清除 LLM 降级窗口失败: %s", e)


# ---------------------------------------------------------------- 手动指定模型


def forced_model() -> str:
    """返回手动指定的模型：`primary` / `backup` / `""`（auto）。"""
    r = _redis()
    if r is not None:
        try:
            raw = r.get(_K_FORCE) or ""
            raw = raw.strip().lower()
            return raw if raw in ALLOWED_FORCE else ""
        except Exception as e:
            logger.debug("读取 LLM 手动指定失败，回退内存: %s", e)
    return _memory["force"]


def set_forced_model(model: str) -> bool:
    """写入手动指定模型。只接受 primary / backup / 空（=自动）。

    手动指定**不带 TTL**：运维点了"切到备用"，就得一直生效到再点回来，
    不能因为进程重启或者过一段时间就悄悄回到主模型。
    """
    value = (model or "").strip().lower()
    if value == "auto":
        value = ""
    if value not in ALLOWED_FORCE:
        return False
    _memory["force"] = value
    r = _redis()
    if r is None:
        return True
    try:
        if value:
            r.set(_K_FORCE, value)
        else:
            r.delete(_K_FORCE)
    except Exception as e:
        logger.warning("写入 LLM 手动指定失败，回退内存: %s", e)
    return True


def reset_local_state() -> None:
    """仅供测试：清空内存兜底状态。"""
    _memory.update({"streak": 0, "streak_at": 0.0, "failover_until": 0.0, "force": ""})
