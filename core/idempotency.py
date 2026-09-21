"""消息幂等：按 MsgId 去重，避免微信重复推送导致重复回复和重复建档"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from config.settings import settings
from core.db import SessionLocal, init_db
from core.models import MessageDedup

logger = logging.getLogger(__name__)


class IdempotencyStore:
    def __init__(self):
        init_db()

    def is_seen(self, msg_id: str, source: str = "") -> bool:
        if not msg_id:
            return False
        session = SessionLocal()
        try:
            row = session.execute(
                select(MessageDedup).where(MessageDedup.msg_id == msg_id)
            ).scalar_one_or_none()
            return row is not None
        finally:
            session.close()

    def mark(self, msg_id: str, source: str = "") -> bool:
        """返回 True 表示首次记录，False 表示重复消息"""
        if not msg_id:
            return True
        session = SessionLocal()
        try:
            session.add(MessageDedup(msg_id=msg_id, source=source))
            session.commit()
            self._purge_if_needed()
            return True
        except IntegrityError:
            session.rollback()
            return False
        finally:
            session.close()

    def _purge_if_needed(self) -> None:
        try:
            cutoff = (
                datetime.now() - timedelta(hours=settings.MESSAGE_DEDUP_TTL_HOURS)
            ).strftime("%Y-%m-%d %H:%M:%S")
            session = SessionLocal()
            try:
                session.execute(
                    delete(MessageDedup).where(MessageDedup.created_at < cutoff)
                )
                session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"幂等记录清理失败: {e}")


idempotency_store = IdempotencyStore()
