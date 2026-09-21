"""
文本处理工具模块
"""
from __future__ import annotations
import re
from typing import List

class TextProcessor:
    @staticmethod
    def clean_text(text: str) -> str:
        """清洗文本：去除多余空格、换行等"""
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def split_sentences(text: str) -> List[str]:
        """按句子分割"""
        sentences = re.split(r"[。！？!?]+", text)
        return [s.strip() for s in sentences if s.strip()]

    @staticmethod
    def extract_keywords(text: str, max_words: int = 10) -> List[str]:
        """简单关键词提取（基于长度过滤）"""
        words = re.findall(r"[\u4e00-\u9fff\w]+", text)
        words = [w for w in words if len(w) >= 2]
        return words[:max_words]

    @staticmethod
    def truncate(text: str, max_length: int = 500) -> str:
        """截断文本"""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."

    @staticmethod
    def is_greeting(text: str) -> bool:
        """判断是否为问候语"""
        greetings = ["你好", "您好", "hi", "hello", "在吗", "在不在", "请问"]
        return any(g in text.lower() for g in greetings)
