"""转人工关键词的唯一来源。

历史问题：`core/agent.py` 硬编码 6 个词、`WECOM_KF_HANDOVER_KEYWORDS` 配 7 个词、
`VISION_HANDOVER_KEYWORDS` 配 9 个词，三个渠道三套规则，同一个客户在不同渠道
说出同一句话，是否转人工的判定结果可能不一致。

现在统一为：全局 `HANDOVER_KEYWORDS` 兜底，渠道级配置仅在显式填写时覆盖。

另外原来使用朴素的子串匹配，`人工` 会命中 `人工智能`——本项目的客户问的恰恰是
AI 课程，这是高频误判。这里先用 FALSE_POSITIVE_GUARDS 把已知的误判片段从文本里
剔除，再做子串匹配。
"""
from __future__ import annotations

from config.settings import settings

# 含「人工」但语义与转人工无关的片段，匹配前先剔除
FALSE_POSITIVE_GUARDS = (
    "人工智能",
    "人工费",
    "人工成本",
    "人工审核",
)

# 各渠道的例外规则（`真人` 只在视觉受管执行器里算转人工信号）
CHANNEL_OVERRIDE_FIELDS = {
    "wecom_kf": "WECOM_KF_HANDOVER_KEYWORDS",
    "wecom": "WECOM_KF_HANDOVER_KEYWORDS",
    "vision": "VISION_HANDOVER_KEYWORDS",
    "vision_agent": "VISION_HANDOVER_KEYWORDS",
}


def _split(raw: str) -> list[str]:
    return [w.strip() for w in (raw or "").split(",") if w.strip()]


def handover_words(channel: str = "") -> list[str]:
    """返回该渠道生效的转人工关键词列表。"""
    field = CHANNEL_OVERRIDE_FIELDS.get((channel or "").strip().lower(), "")
    if field:
        words = _split(getattr(settings, field, "") or "")
        if words:
            return words
    words = _split(getattr(settings, "HANDOVER_KEYWORDS", "") or "")
    if words:
        return words
    return ["人工", "转人工", "人工客服", "找人工", "转客服", "客服电话", "电话联系"]


def contains_handover_keyword(content: str, channel: str = "") -> bool:
    """判断文本是否命中转人工关键词（已排除「人工智能」等误判片段）。"""
    if not content:
        return False
    text = content
    for guard in FALSE_POSITIVE_GUARDS:
        if guard in text:
            text = text.replace(guard, "")
    return any(word in text for word in handover_words(channel))
