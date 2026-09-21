"""对话记忆管理模块（Redis 版）"""
from __future__ import annotations
from typing import Optional
from config.settings import settings
from core.redis_session import session_manager


class ConversationMemory:
    """单个会话的记忆（基于 Redis）"""

    def __init__(self, session_id: str):
        self.session_id = session_id

    def save_context(self, input_text: str, output_text: str):
        """保存一轮对话到 Redis"""
        session_manager.save_context(self.session_id, input_text, output_text)

    def load_history(self, limit: int = 10) -> list[dict]:
        """加载最近 N 轮对话"""
        return session_manager.get_history(self.session_id, limit)

    def get_summary(self, limit: int = 6) -> str:
        """获取格式化的历史摘要（用于 LLM 上下文）"""
        return session_manager.get_history_text(self.session_id, limit)

    def clear(self):
        """清除会话"""
        session_manager.clear_session(self.session_id)


class MemoryManager:
    """会话管理器（Redis 存储，支持多 worker 共享）"""

    def __init__(self):
        # 不再维护本地 dict，全走 Redis
        pass

    def get_or_create(self, session_id: str) -> ConversationMemory:
        """获取或创建会话"""
        return ConversationMemory(session_id)

    def remove(self, session_id: str):
        """删除会话"""
        session_manager.clear_session(session_id)

    def get_active_count(self) -> int:
        """获取活跃会话数"""
        return session_manager.get_active_session_count()


memory_manager = MemoryManager()
