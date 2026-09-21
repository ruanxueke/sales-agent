"""统一回复调度：消息去重 + 同用户串行锁 + 上下文一致 + 多渠道回复。

所有渠道（企业微信自建应用、微信客服、公众号、网页客服等）统一入口：
回调 → enqueue_reply() 入队 Celery → Worker 内加用户锁处理 → 生成回复 → 渠道发送。
Redis 不可用时自动同步兜底，保证单机也能跑通。

幂等约定：
- 有渠道 msg_id 时，去重键 = channel:msg_id（稳定，重试幂等）；
- 无 msg_id 时，去重键按 DEDUP_WINDOW_SECONDS 时间窗生成（默认 30 秒），
  避免「同一客户全天重发同一句话被永久吞掉」；
- 去重键由 enqueue_reply 生成并写入 payload，保证 Celery 重试复用同一个键；
- 分段发送的进度记录在 Redis，重试时只补发未成功的分段，避免客户收到重复内容。
"""
from __future__ import annotations
import hashlib
import logging
import time

from core.redis_session import get_sync_redis

logger = logging.getLogger(__name__)

USER_LOCK_TTL = 120
MSG_DONE_TTL = 86400
LOCK_WAIT = 20.0
DEDUP_WINDOW_SECONDS = 30
PART_PROGRESS_TTL = 3600


class ChannelSenderMissing(RuntimeError):
    """该渠道的发送器尚未接入，属于不可重试错误。"""

    def __init__(self, channel: str):
        super().__init__(channel)
        self.channel = channel


def _redis():
    return get_sync_redis()


def user_lock_key(channel: str, external_id: str) -> str:
    return f"reply:lock:{channel}:{external_id}"


def msg_done_key(msg_key: str) -> str:
    return f"reply:done:{msg_key}"


def part_progress_key(msg_key: str) -> str:
    return f"reply:parts:{msg_key}"


def make_msg_key(channel: str, external_id: str, content: str, msg_id: str = "", bucket: int | None = None) -> str:
    """生成去重键。有 msg_id 用 msg_id；否则按时间窗哈希，允许同一内容稍后再次回复。"""
    if msg_id:
        return f"{channel}:{msg_id}"
    if bucket is None:
        bucket = int(time.time() // DEDUP_WINDOW_SECONDS)
    raw = f"{channel}:{external_id}:{content}:{bucket}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _acquire_lock(redis, key: str) -> bool:
    deadline = time.time() + LOCK_WAIT
    while time.time() < deadline:
        if redis.set(key, "1", nx=True, ex=USER_LOCK_TTL):
            return True
        time.sleep(0.05)
    return False


def _release_lock(redis, key: str):
    try:
        redis.delete(key)
    except Exception as e:
        logger.warning("释放发送锁失败，锁会保留到 TTL 到期: %s", e)


def _generate_reply(content: str, session_id: str, source: str) -> str:
    from core.agent import sales_agent
    return sales_agent.chat(content, session_id=session_id, source=source)


def _should_handover(content: str, channel: str = "") -> bool:
    from core.handover_words import contains_handover_keyword
    return contains_handover_keyword(content, channel)


def _do_kf_handover(external_id: str, open_kfid: str):
    from connectors.wecom import wecom_client
    wecom_client.transfer_kf_session(external_id, open_kfid, service_state=2)
    try:
        from core.handover import handover_manager
        handover_manager.request(session_id=external_id, source="wecom_kf", nickname="", reason="客户要求转人工")
    except Exception as e:
        logger.warning("转人工记录写入失败: %s", e)
    try:
        wecom_client.send_kf(external_id, "好的，正在为您转接人工客服，请稍候。")
    except Exception as e:
        logger.warning("转人工提示发送失败: %s", e)


def _send_parts(
    channel: str,
    external_id: str,
    content: str,
    open_kfid: str = "",
    extra=None,
    redis=None,
    progress_key: str = "",
) -> int:
    """按长度分段发送；redis + progress_key 存在时记录进度，重试只补发未发送的分段。"""
    from config.settings import settings
    from core.message_splitter import split_text

    if channel not in ("wecom_kf", "wecom"):
        raise ChannelSenderMissing(channel)

    parts = split_text(content, getattr(settings, "REPLY_MAX_LENGTH", 50))
    split_delay = getattr(settings, "REPLY_SPLIT_DELAY_SECONDS", 1.5)

    already = 0
    if redis is not None and progress_key:
        try:
            already = int(redis.get(progress_key) or 0)
        except Exception:
            already = 0

    from connectors.wecom import wecom_client
    for idx, part in enumerate(parts):
        if idx < already:
            continue
        if channel == "wecom_kf":
            wecom_client.send_kf(external_id, part)
        else:
            wecom_client.send_text(external_id, part)
        if redis is not None and progress_key:
            try:
                redis.set(progress_key, idx + 1, ex=PART_PROGRESS_TTL)
            except Exception as e:
                logger.warning("分片发送进度写入失败，重试时可能重复发送该分片: %s", e)
        if idx < len(parts) - 1:
            time.sleep(split_delay)
    return len(parts)


def _deliver(channel: str, external_id: str, content: str, open_kfid: str, extra: dict, redis, msg_key: str) -> dict:
    """发送回复；渠道未接入返回结构化失败，不假装成功。"""
    try:
        sent = _send_parts(
            channel,
            external_id,
            content,
            open_kfid,
            extra,
            redis=redis,
            progress_key=part_progress_key(msg_key) if redis is not None else "",
        )
    except ChannelSenderMissing as exc:
        logger.error("渠道 %s 的发送器尚未接入，回复未发出：%s", exc.channel, content[:80])
        return {"ok": False, "retryable": False, "error": f"渠道 {exc.channel} 发送器未接入"}
    except Exception as exc:
        logger.error("渠道 %s 发送失败（可重试）：%s", channel, exc)
        return {"ok": False, "retryable": True, "error": f"发送失败: {exc}"}
    return {"ok": True, "sent": sent}


def run_reply_task(payload: dict) -> dict:
    channel = payload.get("channel") or ""
    external_id = payload.get("external_id") or ""
    content = payload.get("content") or ""
    msg_id = payload.get("msg_id") or ""
    session_id = payload.get("session_id") or ""
    open_kfid = payload.get("open_kfid") or ""
    source = payload.get("source") or channel
    extra = payload.get("extra") or {}
    if not external_id or not content:
        return {"ok": False, "retryable": False, "error": "缺少用户或内容"}

    redis = _redis()
    # 优先复用入队时生成的键，保证 Celery 重试幂等
    msg_key = payload.get("msg_key") or make_msg_key(channel, external_id, content, msg_id)
    done_key = msg_done_key(msg_key)

    if redis is None:
        # 无 Redis：同步兜底（单机模式），不做跨进程去重
        reply = _generate_reply(content, session_id or external_id, source)
        return _deliver(channel, external_id, reply, open_kfid, extra, None, msg_key)

    if redis.exists(done_key):
        return {"ok": True, "deduped": True}

    lock_key = user_lock_key(channel, external_id)
    if not _acquire_lock(redis, lock_key):
        # 同用户上一条还在处理：属于可重试错误，交给 Celery 退避重试
        return {"ok": False, "retryable": True, "error": "用户处理锁等待超时"}
    try:
        # 拿到锁后二次检查，防止并发重复
        if redis.exists(done_key):
            return {"ok": True, "deduped": True}
        if channel == "wecom_kf" and _should_handover(content, channel):
            try:
                _do_kf_handover(external_id, open_kfid)
            except Exception as e:
                logger.error("微信客服转人工失败: %s", e)
            redis.set(done_key, "1", ex=MSG_DONE_TTL)
            return {"ok": True, "handover": True}

        reply = _generate_reply(content, session_id or external_id, source)
        result = _deliver(channel, external_id, reply, open_kfid, extra, redis, msg_key)
        if not result.get("ok"):
            return result
        redis.set(done_key, "1", ex=MSG_DONE_TTL)
        try:
            redis.delete(part_progress_key(msg_key))
        except Exception as e:
            logger.debug("run_reply_task 异常已忽略: %s", e)
        return result
    finally:
        _release_lock(redis, lock_key)


def enqueue_reply(
    channel: str,
    external_id: str,
    content: str,
    msg_id: str = "",
    session_id: str = "",
    open_kfid: str = "",
    source: str = "",
    extra: dict | None = None,
) -> dict:
    """渠道回调统一入口：入队 Celery；不可用时同步兜底。"""
    payload = {
        "channel": channel,
        "external_id": external_id,
        "content": content,
        "msg_id": msg_id or "",
        "session_id": session_id or "",
        "open_kfid": open_kfid or "",
        "source": source or channel,
        "extra": extra or {},
    }
    # 在生产者侧固化去重键：保证重试复用同一个键
    payload["msg_key"] = make_msg_key(channel, external_id, content, msg_id or "")
    try:
        from core.tasks import send_channel_reply_task
        send_channel_reply_task.delay(payload)
        return {"ok": True, "queued": True}
    except Exception as e:
        logger.warning("统一回复入队失败，同步兜底: %s", e)
        return run_reply_task(payload)
