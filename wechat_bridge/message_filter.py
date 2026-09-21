"""消息标准化、白名单过滤和指纹生成。"""
from __future__ import annotations

import hashlib

from wechat_bridge.config import BridgeConfig, TargetConfig


MEDIA_PLACEHOLDERS = ("[图片]", "[语音]", "[视频]", "[文件]", "[分享")


def message_fingerprint(
    account_id: str,
    target_username: str,
    created_at: int,
    sender_name: str,
    content: str,
) -> str:
    raw = f"{account_id}:{target_username}:{created_at}:{sender_name}:{content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_message(
    raw: dict,
    config: BridgeConfig,
    target: TargetConfig,
) -> dict | None:
    content = str(raw.get("text") or raw.get("content") or "").strip()
    created_at = int(raw.get("time") or raw.get("created_at") or 0)
    sender_name = str(raw.get("sender") or "").strip()
    target_name = str(raw.get("target_name") or target.target_name).strip()
    target_username = str(
        raw.get("target_username") or target.target_username
    ).strip()
    if not content or not created_at:
        return None
    if bool(raw.get("is_self")):
        return None
    if sender_name and sender_name in set(config.self_names):
        return None
    if not config.allow_media_placeholders and any(
        content.startswith(prefix) for prefix in MEDIA_PLACEHOLDERS
    ):
        return None
    fingerprint = message_fingerprint(
        config.account_id,
        target_username,
        created_at,
        sender_name,
        content,
    )
    return {
        "tenant_id": config.tenant_id,
        "account_id": config.account_id,
        "channel": "personal_wechat",
        "target_type": target.target_type,
        "target_name": target_name,
        "target_username": target_username,
        "sender_name": sender_name,
        "sender_username": str(raw.get("sender_username") or ""),
        "message_id": fingerprint,
        "content": content,
        "created_at": created_at,
        "is_self": bool(raw.get("is_self")),
        "msg_type": str(raw.get("type") or "text"),
        "mode": target.mode,
    }


# 含「人工」但语义与转人工无关的片段，匹配前先剔除
# （本项目客户问的正是 AI 课程，「人工智能」是高频词，朴素子串匹配会误判）
_HANDOVER_FALSE_POSITIVES = ("人工智能", "人工费", "人工成本", "人工审核")


def contains_handover_keyword(content: str, target: TargetConfig) -> bool:
    if not content:
        return False
    text = content
    for guard in _HANDOVER_FALSE_POSITIVES:
        if guard in text:
            text = text.replace(guard, "")
    return any(keyword and keyword in text for keyword in target.handover_keywords)
