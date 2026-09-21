"""回复拆分：超过指定字数时，按标点拆成多条，保持语义不变"""
from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff，。！？；、：]+")
_WEAK = set("，,、：: ")
_STRONG = set("。！？!?；;\n")


def _split_sentences(text: str) -> list[str]:
    items: list[str] = []
    buf = ""
    i = 0
    n = len(text)
    while i < n:
        m = _URL_RE.match(text, i)
        if m:
            if buf.strip():
                items.append(buf.strip())
            items.append(m.group(0))
            buf = ""
            i = m.end()
            continue
        ch = text[i]
        buf += ch
        if ch in _STRONG:
            items.append(buf.strip())
            buf = ""
        i += 1
    if buf.strip():
        items.append(buf.strip())
    return [x for x in items if x]


def _cut_long_sentence(sentence: str, max_len: int) -> list[str]:
    parts: list[str] = []
    piece = sentence
    while len(piece) > max_len:
        cut = -1
        for j in range(max_len - 1, -1, -1):
            if piece[j] in _WEAK or piece[j] in _STRONG:
                cut = j + 1
                break
        if cut <= 0:
            cut = max_len
        parts.append(piece[:cut].strip())
        piece = piece[cut:].strip()
    if piece:
        parts.append(piece)
    return [x for x in parts if x]


def split_text(text: str, max_len: int = 50) -> list[str]:
    """把回复拆成不超过 max_len 的若干条，URL 保持完整不拆分。

    只在累计超过 max_len 时才拆分，短句会合并，尽量少拆。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    sentences = _split_sentences(text)
    out: list[str] = []
    cur = ""
    for s in sentences:
        if len(s) > max_len:
            if cur:
                out.append(cur)
                cur = ""
            if s.startswith(("http://", "https://")):
                out.append(s)
            else:
                out.extend(_cut_long_sentence(s, max_len))
            continue
        if not cur:
            cur = s
        elif len(cur) + len(s) <= max_len:
            cur += s
        else:
            out.append(cur)
            cur = s
    if cur:
        out.append(cur)
    return [x for x in out if x]
