"""赢单引擎：竞品应对、差异点、证据库、关键时刻工具"""
from __future__ import annotations
import logging
from datetime import datetime

from sqlalchemy import or_, select

from core.db import init_db, session_scope
from core.models import Differentiator, EvidenceLibrary, KeyMomentTool

logger = logging.getLogger(__name__)

COMPETITOR_WORDS = ["其他家", "别家", "别处", "竞品", "对比", "他们", "对方", "比价", "更便宜", "更优惠", "另一家", "朋友推荐", "已经在用"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _fill(kwargs: dict, allowed: set) -> dict:
    return {k: v for k, v in kwargs.items() if k in allowed and v is not None}


class WinningManager:
    def __init__(self):
        init_db()

    # ---------- 差异点 ----------
    def list_differentiators(self, active_only: bool = False) -> list[dict]:
        with session_scope() as session:
            query = select(Differentiator).order_by(Differentiator.id.desc())
            if active_only:
                query = query.where(Differentiator.active.is_(True))
            return [_row_to_dict(r) for r in session.execute(query).scalars().all()]

    def create_differentiator(self, **fields) -> dict:
        allowed = {"product", "differentiator", "evidence", "customer_concern"}
        with session_scope() as session:
            obj = Differentiator(**{**_fill(fields, allowed), "active": True})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_differentiator(self, item_id: int, **fields) -> dict | None:
        allowed = {"product", "differentiator", "evidence", "customer_concern", "active"}
        with session_scope() as session:
            obj = session.get(Differentiator, item_id)
            if not obj:
                return None
            for k, v in _fill(fields, allowed).items():
                setattr(obj, k, v)
            return _row_to_dict(obj)

    # ---------- 证据库 ----------
    def list_evidence(self, evidence_type: str = "", keyword: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(EvidenceLibrary).order_by(EvidenceLibrary.id.desc())
            if evidence_type:
                query = query.where(EvidenceLibrary.evidence_type == evidence_type)
            if keyword:
                like = f"%{keyword}%"
                query = query.where(or_(EvidenceLibrary.title.like(like), EvidenceLibrary.content.like(like), EvidenceLibrary.scenario.like(like)))
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    def create_evidence(self, **fields) -> dict:
        allowed = {"evidence_type", "title", "content", "link", "scenario"}
        with session_scope() as session:
            obj = EvidenceLibrary(**{**_fill(fields, allowed), "active": True})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_evidence(self, item_id: int, **fields) -> dict | None:
        allowed = {"evidence_type", "title", "content", "link", "scenario", "active"}
        with session_scope() as session:
            obj = session.get(EvidenceLibrary, item_id)
            if not obj:
                return None
            for k, v in _fill(fields, allowed).items():
                setattr(obj, k, v)
            return _row_to_dict(obj)

    # ---------- 关键时刻工具 ----------
    def list_tools(self, tool_type: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(KeyMomentTool).order_by(KeyMomentTool.id.desc())
            if tool_type:
                query = query.where(KeyMomentTool.tool_type == tool_type)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    def create_tool(self, **fields) -> dict:
        allowed = {"tool_type", "name", "description", "trigger_scene"}
        with session_scope() as session:
            obj = KeyMomentTool(**{**_fill(fields, allowed), "active": True})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_tool(self, item_id: int, **fields) -> dict | None:
        allowed = {"tool_type", "name", "description", "trigger_scene", "active"}
        with session_scope() as session:
            obj = session.get(KeyMomentTool, item_id)
            if not obj:
                return None
            for k, v in _fill(fields, allowed).items():
                setattr(obj, k, v)
            return _row_to_dict(obj)

    # ---------- 触发与上下文 ----------
    def is_winning_scene(self, message: str) -> bool:
        return any(w in message for w in COMPETITOR_WORDS)

    def retrieve_context(self, message: str) -> str:
        blocks = []
        for item in self.list_differentiators(active_only=True)[:5]:
            blocks.append(
                f"差异点：{item.get('differentiator')}（产品：{item.get('product')}，"
                f"对应客户在意项：{item.get('customer_concern')}）\n证据：{item.get('evidence')}"
            )
        for item in self.list_evidence(limit=5):
            blocks.append(
                f"证据（{item.get('evidence_type')}）：{item.get('title')}\n"
                f"内容：{item.get('content')}\n场景：{item.get('scenario')}"
            )
        for item in self.list_tools(limit=5):
            blocks.append(
                f"关键时刻工具（{item.get('tool_type')}）：{item.get('name')}\n"
                f"说明：{item.get('description')}\n适用场景：{item.get('trigger_scene')}"
            )
        return "\n\n".join(blocks)



    def delete_differentiator(self, item_id: int) -> bool:
        with session_scope() as session:
            obj = session.get(Differentiator, item_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_evidence(self, item_id: int) -> bool:
        with session_scope() as session:
            obj = session.get(EvidenceLibrary, item_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_tool(self, item_id: int) -> bool:
        with session_scope() as session:
            obj = session.get(KeyMomentTool, item_id)
            if not obj:
                return False
            session.delete(obj)
            return True


winning_manager = WinningManager()
