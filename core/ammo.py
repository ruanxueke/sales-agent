"""话术弹药库：产品知识、异议应答、竞品应对、跟进话术、销售案例投喂学习"""
from __future__ import annotations
import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import or_, select

from core.db import init_db, session_scope
from core.models import (
    CompetitorResponse,
    FollowupScript,
    ObjectionResponse,
    ProductKnowledge,
    SalesCase,
)

logger = logging.getLogger(__name__)

SALES_STATUSES = [
    "new_lead",
    "replied",
    "hesitating",
    "comparing",
    "read_no_reply",
    "rejected",
    "won",
    "lost",
]

SALES_STATUS_LABELS = {
    "new_lead": "新线索",
    "replied": "已回复",
    "hesitating": "犹豫",
    "comparing": "比价",
    "read_no_reply": "已读不回",
    "rejected": "明确拒绝",
    "won": "已成交",
    "lost": "流失",
}

STATUS_NEXT = {
    "new_lead": {"hours": 2, "reason": "首轮跟进，给案例或资料验证价值", "goal": "回复并进入已回复"},
    "replied": {"hours": 24, "reason": "围绕上次顾虑给证据，推进需求", "goal": "深挖需求并记录顾虑"},
    "hesitating": {"hours": 24, "reason": "找出真实顾虑，用试用/案例/承诺降低风险", "goal": "确认卡点并给下一步"},
    "comparing": {"hours": 48, "reason": "重建选择标准，绑定差异点并给证据", "goal": "客户同意试用或体验"},
    "read_no_reply": {"hours": 72, "reason": "换一个新钩子重新激活，不重复上次内容", "goal": "重新打开对话"},
    "rejected": {"hours": 720, "reason": "尊重拒绝，30 天后用行业内容低成本种草", "goal": "保持联系，等待时机"},
    "won": {"hours": 168, "reason": "交付体验回访，教使用", "goal": "确认体验并推动复购/转介绍"},
    "lost": {"hours": 720, "reason": "月度唤醒，用新品/权益/转介绍钩子", "goal": "低成本召回"},
}

COMPETITOR_WORDS = ["其他家", "别家", "别处", "竞品", "对比", "他们", "对方", "比价", "更便宜", "更优惠", "另一家", "朋友推荐"]
REJECT_WORDS = ["不买了", "不要了", "不需要", "别烦我", "不用了", "不考虑", "不感兴趣", "别再联系", "拉黑"]
HESITATE_WORDS = ["再考虑", "考虑一下", "想想", "考虑考虑", "再看看", "商量一下", "过几天"]
COMPARE_WORDS = ["比一下", "对比", "竞品", "别家", "其他家", "他们", "便宜", "性价比"]
CONCERN_WORDS = {
    "怕没效果": ["没效果", "没用", "学不会", "怕踩坑", "真的有用吗", "靠谱吗", "包教会吗", "包教包会"],
    "怕没时间": ["没时间", "太忙", "时间不够", "没空", "工作忙"],
    "价格贵": ["太贵", "贵", "便宜", "优惠", "打折", "价格", "1980", "1980元"],
    "怕骗人": ["骗", "割韭菜", "智商税", "套路", "不放心"],
    "担心售后": ["售后", "没人管", "买完怎么办", "找不到人", "服务"],
}
SELECTION_WORDS = {
    "效果": ["效果", "能赚", "变现", "学会", "掌握", "实用"],
    "价格": ["价格", "便宜", "优惠", "划算", "贵"],
    "售后": ["售后", "服务", "包教", "保障", "退换"],
    "省心": ["省心", "方便", "简单", "省事", "托管"],
}
EVIDENCE_WORDS = ["案例", "学员", "试用", "试听", "体验", "退换", "包教", "证据", "截图", "数据", "评价"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _fill(kwargs: dict, allowed: set) -> dict:
    return {k: v for k, v in kwargs.items() if k in allowed and v is not None}


class AmmoManager:
    def __init__(self):
        # 不在 __init__ 里碰数据库。原来这段 init_db()+_seed() 跑在模块导入期，
        # 于是"import core.ammo"就等于"必须有一张已经建好且可读的 product_knowledge
        # 表"；表缺失时抛的是 SQLAlchemy 的样板错误，看不出是哪张表，而且会把整个
        # 进程一起带下去（导入期异常没法降级）。改成首次使用时惰性初始化。
        self._ready = False
        self._ready_lock = threading.Lock()

    @contextmanager
    def _db(self):
        """业务方法统一从这里取会话，顺带保证首次调用前已完成初始化与种子写入。"""
        self._ensure_ready()
        with session_scope() as session:
            yield session

    def _ensure_ready(self) -> None:
        if self._ready:
            return
        with self._ready_lock:
            if self._ready:
                return
            try:
                init_db()
                self._seed()
            except Exception as e:
                # 不吞掉：调用方要看到真实失败。但记一条能看懂的日志，并且**不置位**
                # _ready，所以迁移补上表之后再调用会自动恢复，不需要重启进程。
                logger.warning("弹药库初始化失败（表缺失或数据库不可用），下次调用会重试: %s", e)
                raise
            self._ready = True

    # ---------- 种子数据 ----------
    def _seed(self) -> None:
        # 必须直接用 session_scope：走 self._db() 会变成 _db -> _ensure_ready
        # -> _seed -> _db 自锁。
        with session_scope() as session:
            count = session.execute(select(ProductKnowledge)).scalars().all()
            if count:
                return
            session.add(ProductKnowledge(
                product_name="普通人AI课程",
                target_customer="想学 AI 但零基础或刚入门的普通人",
                solves="从零学会使用 AI 完成日常办公、内容创作、副业变现",
                selling_points="包教会；从 AI 工具操作到实际项目拆解；每一步带您跑通",
                price="1980 元",
                after_sales="购买课程后包教会，学完仍可继续答疑",
                risk_limits="不承诺百分之百变现，不夸大收益",
                proof="待补充学员案例",
                active=True,
            ))
            session.add(FollowupScript(
                followup_scene="new_lead",
                trigger_condition="新线索首轮跟进",
                value_point="同场景案例",
                script_example="上次您说想了解AI副业，这个案例和您的情况很像，先给您看看。",
                next_goal="约体验或看详情",
                delay_hours=2,
                active=True,
            ))

    # ---------- 产品知识 ----------
    def list_products(self, active_only: bool = False) -> list[dict]:
        with self._db() as session:
            query = select(ProductKnowledge).order_by(ProductKnowledge.id.desc())
            if active_only:
                query = query.where(ProductKnowledge.active.is_(True))
            return [_row_to_dict(r) for r in session.execute(query).scalars().all()]

    def create_product(self, **fields) -> dict:
        allowed = {"product_name", "target_customer", "solves", "selling_points", "price", "after_sales", "risk_limits", "proof"}
        with self._db() as session:
            obj = ProductKnowledge(**_fill(fields, allowed))
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_product(self, product_id: int, **fields) -> dict | None:
        allowed = {"product_name", "target_customer", "solves", "selling_points", "price", "after_sales", "risk_limits", "proof", "active"}
        with self._db() as session:
            obj = session.get(ProductKnowledge, product_id)
            if not obj:
                return None
            for k, v in _fill(fields, allowed).items():
                setattr(obj, k, v)
            obj.updated_at = _now()
            return _row_to_dict(obj)

    # ---------- 异议应答 ----------
    def list_objections(self, active_only: bool = False) -> list[dict]:
        with self._db() as session:
            query = select(ObjectionResponse).order_by(ObjectionResponse.sort, ObjectionResponse.id.desc())
            if active_only:
                query = query.where(ObjectionResponse.active.is_(True))
            return [_row_to_dict(r) for r in session.execute(query).scalars().all()]

    def create_objection(self, **fields) -> dict:
        allowed = {"trigger_scene", "standard_reply", "evidence", "next_step", "sort"}
        with self._db() as session:
            obj = ObjectionResponse(**{**_fill(fields, allowed), "active": True})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_objection(self, objection_id: int, **fields) -> dict | None:
        allowed = {"trigger_scene", "standard_reply", "evidence", "next_step", "sort", "active"}
        with self._db() as session:
            obj = session.get(ObjectionResponse, objection_id)
            if not obj:
                return None
            for k, v in _fill(fields, allowed).items():
                setattr(obj, k, v)
            return _row_to_dict(obj)

    # ---------- 竞品应对 ----------
    def list_competitors(self, active_only: bool = False) -> list[dict]:
        with self._db() as session:
            query = select(CompetitorResponse).order_by(CompetitorResponse.id.desc())
            if active_only:
                query = query.where(CompetitorResponse.active.is_(True))
            return [_row_to_dict(r) for r in session.execute(query).scalars().all()]

    def create_competitor(self, **fields) -> dict:
        allowed = {"competitor", "customer_saying", "differentiator_1", "differentiator_2", "differentiator_3", "standard_reply"}
        with self._db() as session:
            obj = CompetitorResponse(**{**_fill(fields, allowed), "active": True})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_competitor(self, competitor_id: int, **fields) -> dict | None:
        allowed = {"competitor", "customer_saying", "differentiator_1", "differentiator_2", "differentiator_3", "standard_reply", "active"}
        with self._db() as session:
            obj = session.get(CompetitorResponse, competitor_id)
            if not obj:
                return None
            for k, v in _fill(fields, allowed).items():
                setattr(obj, k, v)
            return _row_to_dict(obj)

    # ---------- 跟进话术 ----------
    def list_scripts(self, scene: str = "", active_only: bool = True) -> list[dict]:
        with self._db() as session:
            query = select(FollowupScript).order_by(FollowupScript.delay_hours, FollowupScript.id)
            if scene:
                query = query.where(FollowupScript.followup_scene == scene)
            if active_only:
                query = query.where(FollowupScript.active.is_(True))
            return [_row_to_dict(r) for r in session.execute(query).scalars().all()]

    def create_script(self, **fields) -> dict:
        allowed = {"followup_scene", "trigger_condition", "value_point", "script_example", "next_goal", "delay_hours"}
        with self._db() as session:
            obj = FollowupScript(**{**_fill(fields, allowed), "active": True})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def update_script(self, script_id: int, **fields) -> dict | None:
        allowed = {"followup_scene", "trigger_condition", "value_point", "script_example", "next_goal", "delay_hours", "active"}
        with self._db() as session:
            obj = session.get(FollowupScript, script_id)
            if not obj:
                return None
            for k, v in _fill(fields, allowed).items():
                setattr(obj, k, v)
            return _row_to_dict(obj)

    # ---------- 销售案例投喂 ----------
    def create_case(self, **fields) -> dict:
        allowed = {"title", "case_type", "source", "channel", "content", "key_turns", "objections", "winning_points", "mistakes", "result", "tags"}
        with self._db() as session:
            obj = SalesCase(**{**_fill(fields, allowed), "active": True})
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def analyze_case(self, content: str, title: str = "") -> dict:
        """轻量规则拆解案例：成交路径、失败原因、关键话术、异议、标签（不额外调用 LLM）"""
        lines = [x.strip() for x in (content or "").splitlines() if x.strip()]
        key_turns = []
        objections = []
        winning_points = []
        mistakes = []
        tags = set()
        for line in lines:
            if any(k in line for k in ("客户", "用户", "对方", "学员")):
                key_turns.append(line[:200])
            if any(k in line for k in CONCERN_WORDS) or any(k in line for k in HESITATE_WORDS):
                objections.append(line[:200])
            if any(k in line for k in ("成交", "下单", "报名", "付费", "买了", "转化")):
                winning_points.append(line[:200])
                tags.add("成交")
            if any(k in line for k in ("失败", "流失", "没回", "拒", "退了")):
                mistakes.append(line[:200])
                tags.add("失败")
            if any(k in line for k in ("话术", "回复", "答", "说")):
                tags.add("话术")
        if title:
            tags.add(title[:20])
        return {
            "key_turns": key_turns,
            "objections": objections,
            "winning_points": winning_points,
            "mistakes": mistakes,
            "tags": "、".join(sorted(tags)),
            "case_type": "failure" if mistakes and not winning_points else "success" if winning_points else "general",
        }

    def import_case(self, content: str, title: str = "", channel: str = "") -> dict:
        analysis = self.analyze_case(content, title)
        return self.create_case(
            title=title or f"案例 {datetime.now().strftime('%m%d%H%M%S')}",
            case_type=analysis["case_type"],
            source="manual",
            channel=channel or "",
            content=content,
            key_turns="\n".join(analysis["key_turns"]),
            objections="\n".join(analysis["objections"]),
            winning_points="\n".join(analysis["winning_points"]),
            mistakes="\n".join(analysis["mistakes"]),
            result=analysis["case_type"],
            tags=analysis["tags"],
        )

    def list_cases(self, case_type: str = "", keyword: str = "", limit: int = 200) -> list[dict]:
        with self._db() as session:
            query = select(SalesCase).order_by(SalesCase.id.desc())
            if case_type:
                query = query.where(SalesCase.case_type == case_type)
            if keyword:
                like = f"%{keyword}%"
                query = query.where(or_(
                    SalesCase.title.like(like),
                    SalesCase.content.like(like),
                    SalesCase.tags.like(like),
                ))
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    # ---------- 弹药库检索（供 Agent 拼入上下文） ----------
    def retrieve_context(self, message: str, sales_status: str = "") -> str:
        blocks = []
        products = self.list_products(active_only=True)
        for p in products[:1]:
            blocks.append(
                f"产品：{p.get('product_name')}\n适用：{p.get('target_customer')}\n"
                f"解决：{p.get('solves')}\n卖点：{p.get('selling_points')}\n"
                f"价格：{p.get('price')}\n售后：{p.get('after_sales')}\n"
                f"限制：{p.get('risk_limits')}\n证明：{p.get('proof')}"
            )

        for obj in self.list_objections(active_only=True):
            scene = obj.get("trigger_scene") or ""
            if scene and any(k in message for k in CONCERN_WORDS.get(scene, [scene])):
                blocks.append(
                    f"异议：{scene}\n标准回复：{obj.get('standard_reply')}\n"
                    f"证据：{obj.get('evidence')}\n下一步：{obj.get('next_step')}"
                )

        if any(k in message for k in COMPETITOR_WORDS):
            for obj in self.list_competitors(active_only=True):
                blocks.append(
                    f"竞品应对：{obj.get('competitor')}｜{obj.get('customer_saying')}\n"
                    f"差异点：{obj.get('differentiator_1')} / {obj.get('differentiator_2')} / {obj.get('differentiator_3')}\n"
                    f"标准回应：{obj.get('standard_reply')}"
                )

        cases = self.list_cases(case_type="success", limit=3)
        for case in cases[:2]:
            blocks.append(
                f"案例：{case.get('title')}（{case.get('case_type')}）\n"
                f"关键过程：{case.get('key_turns')}\n"
                f"异议处理：{case.get('objections')}\n"
                f"成交要点：{case.get('winning_points')}"
            )

        if sales_status:
            scripts = self.list_scripts(scene=sales_status, active_only=True)
            for script in scripts[:1]:
                blocks.append(
                    f"跟进话术（{script.get('followup_scene')}）：{script.get('script_example')} "
                    f"｜价值点：{script.get('value_point')}｜下一步：{script.get('next_goal')}"
                )

        return "\n\n".join(blocks)



    def delete_product(self, product_id: int) -> bool:
        with self._db() as session:
            obj = session.get(ProductKnowledge, product_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_objection(self, objection_id: int) -> bool:
        with self._db() as session:
            obj = session.get(ObjectionResponse, objection_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_competitor(self, competitor_id: int) -> bool:
        with self._db() as session:
            obj = session.get(CompetitorResponse, competitor_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_script(self, script_id: int) -> bool:
        with self._db() as session:
            obj = session.get(FollowupScript, script_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def delete_case(self, case_id: int) -> bool:
        with self._db() as session:
            obj = session.get(SalesCase, case_id)
            if not obj:
                return False
            session.delete(obj)
            return True


ammo_manager = AmmoManager()
