"""读写分离路由 — 查询走只读引擎，写操作走主引擎

用法：
    from core.db_router import read_only

    @read_only
    def list_customers():
        with session_scope() as session:
            return session.query(Customer).all()

    # 或者直接在函数内使用
    def get_stats():
        with session_scope(read_only=True) as session:
            return session.query(func.count(Customer.id)).scalar()
"""
from __future__ import annotations
import functools
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def read_only(func: Callable) -> Callable:
    """装饰器：标记函数为只读操作（走只读引擎）"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    wrapper._db_read_only = True
    return wrapper


def is_read_only(func: Callable) -> bool:
    """检查函数是否标记为只读"""
    return getattr(func, "_db_read_only", False)
