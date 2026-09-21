"""消息拆分测试：超过50字按标点拆、短句合并、链接完整"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message_splitter import split_text


def main() -> int:
    cases = [
        ("短回复", 3, 1),
        ("abcdefghijklmnopqrstuvwxyz1234567890", 36, 1),
        ("abcdefghijklmnopqrstuvwxyz123456789012345678901234567890", 56, 2),
        ("这个优惠价是198元，原价1980元，课程内容完全一样。您把海报转到朋友圈3天就能参加，我先发您海报看看？", 53, 2),
        ("您直接点这个链接就能付款，微信支付就行：https://7rp4r.xetslk.com/s/2iAzMg 付款后课程马上就能看，随时可以开始学。", 73, 3),
    ]
    for text, length, expected in cases:
        parts = split_text(text, 50)
        assert len(text) == length, f"用例长度不符: {len(text)} != {length}"
        assert len(parts) == expected, f"应拆{expected}条，实际{len(parts)}条: {parts}"
        for p in parts:
            assert len(p) <= 50 or p.startswith("http"), f"片段超长: {p}"

    parts = split_text("链接：https://7rp4r.xetslk.com/s/2iAzMg 后面还有一句话。", 50)
    full = "https://7rp4r.xetslk.com/s/2iAzMg"
    assert full in "".join(parts), "链接内容必须完整保留"
    assert not any(p in ("https:", "http:") for p in parts), "链接不能被截断"
    assert not any(p.startswith("//") for p in parts), "链接不能被截断"
    print("消息拆分测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
