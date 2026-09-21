"""会话结构化输出：Solda 客户状态机、每轮摘要、会话指标"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import ConversationMetric, ConversationSummary

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

REJECT_WORDS = ["不买了", "不要了", "不需要", "别烦我", "不用了", "不考虑", "不感兴趣", "别再联系", "拉黑", "别找我", "不要给我发"]
HESITATE_WORDS = ["再考虑", "考虑一下", "想想", "考虑考虑", "再看看", "商量一下", "过几天", "犹豫"]
COMPARE_WORDS = ["比一下", "对比", "竞品", "别家", "其他家", "他们", "便宜", "性价比", "其他平台", "其他机构"]
BUY_WORDS = ["报名", "购买", "下单", "开课", "我买", "怎么付", "付款", "支付", "我要学", "成交"]
CONCERN_MAP = {
    "怕没效果": ["没效果", "没用", "学不会", "怕踩坑", "真的有用吗", "靠谱吗", "包教会吗", "包教包会"],
    "怕没时间": ["没时间", "太忙", "时间不够", "没空", "工作忙"],
    "价格贵": ["太贵", "贵", "便宜", "优惠", "打折", "价格", "1980"],
    "怕骗人": ["骗", "割韭菜", "智商税", "套路", "不放心"],
    "担心售后": ["售后", "没人管", "买完怎么办", "找不到人", "服务"],
}
SELECTION_MAP = {
    "效果": ["效果", "能赚", "变现", "学会", "掌握", "实用"],
    "价格": ["价格", "便宜", "优惠", "划算", "贵"],
    "售后": ["售后", "服务", "包教", "保障", "退换"],
    "省心": ["省心", "方便", "简单", "省事", "托管"],
}
EVIDENCE_MAP = ["案例", "学员", "试用", "试听", "体验", "退换", "包教", "证据", "截图", "数据", "评价", "承诺"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _future(hours: int) -> str:
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def detect_status(message: str, current_stage: str = "") -> str:
    """规则版客户状态判断，不额外调用 LLM，保证大脑层不动"""
    if any(w in message for w in BUY_WORDS):
        return "won"
    if any(w in message for w in REJECT_WORDS):
        return "rejected"
    if any(w in message for w in COMPARE_WORDS):
        return "comparing"
    if any(w in message for w in HESITATE_WORDS):
        return "hesitating"
    if current_stage in ("enrolled", "won", "after_sales"):
        return "won"
    if current_stage and current_stage not in ("new",):
        return "replied"
    return "new_lead"


def detect_concern(message: str) -> str:
    for concern, words in CONCERN_MAP.items():
        if any(w in message for w in words):
            return concern
    return ""


def detect_selection(message: str) -> str:
    for criteria, words in SELECTION_MAP.items():
        if any(w in message for w in words):
            return criteria
    return ""


def detect_evidence(reply: str) -> str:
    hits = [k for k in EVIDENCE_MAP if k in (reply or "")]
    return "、".join(hits[:3])


def build_summary(message: str, reply: str, session_id: str, source: str = "", stage: str = "") -> dict:
    status = detect_status(message, stage)
    concern = detect_concern(message)
    criteria = detect_selection(message)
    evidence = detect_evidence(reply)
    reason_map = {
        "new_lead": "首轮跟进，给案例或资料验证价值",
        "replied": "围绕上次顾虑给证据，推进需求",
        "hesitating": "找出真实顾虑，用试用/案例/承诺降低风险",
        "comparing": "重建选择标准，绑定差异点并给证据",
        "read_no_reply": "换一个新钩子重新激活",
        "rejected": "尊重拒绝，30 天后用行业内容低成本种草",
        "won": "交付体验回访，教使用",
        "lost": "月度唤醒，用新品/权益/转介绍钩子",
    }
    goal_map = {
        "new_lead": "回复并进入已回复",
        "replied": "深挖需求并记录顾虑",
        "hesitating": "确认卡点并给下一步",
        "comparing": "客户同意试用或体验",
        "read_no_reply": "重新打开对话",
        "rejected": "保持联系，等待时机",
        "won": "确认体验并推动复购/转介绍",
        "lost": "低成本召回",
    }
    hours_map = {"new_lead": 2, "replied": 24, "hesitating": 24, "comparing": 48, "read_no_reply": 72, "rejected": 720, "won": 168, "lost": 720}
    return {
        "session_id": session_id,
        "source": source,
        "sales_status": status,
        "core_concern": concern,
        "selection_criteria": criteria,
        "evidence_given": evidence,
        "next_follow_time": _future(hours_map.get(status, 24)),
        "next_follow_reason": reason_map.get(status, ""),
        "next_goal": goal_map.get(status, ""),
    }


class ConversationManager:
    def __init__(self):
        init_db()

    def record(self, message: str, reply: str, session_id: str, customer: dict = None, lead: dict = None, source: str = "") -> dict:
        stage = (customer or lead or {}).get("stage") or ""
        summary = build_summary(message, reply, session_id, source=source, stage=stage)
        customer_id = (customer or {}).get("id")
        lead_id = (lead or {}).get("id")
        with session_scope() as session:
            obj = ConversationSummary(
                session_id=session_id,
                customer_id=customer_id,
                lead_id=lead_id,
                source=source,
                sales_status=summary["sales_status"],
                core_concern=summary["core_concern"],
                selection_criteria=summary["selection_criteria"],
                evidence_given=summary["evidence_given"],
                next_follow_time=summary["next_follow_time"],
                next_follow_reason=summary["next_follow_reason"],
                next_goal=summary["next_goal"],
                raw_json=json.dumps(summary, ensure_ascii=False),
            )
            session.add(obj)
        self._record_metric(summary, customer_id, lead_id, source, stage, reply)

        if customer_id:
            self._update_customer_status(customer_id, summary["sales_status"])
            try:
                from core.sales_crm import crm
                crm.update_profile(customer_id, next_follow_up=summary["next_follow_time"])
            except Exception as e:
                logger.debug("ConversationManager.record 异常已忽略: %s", e)
        return summary

    def _record_metric(self, summary: dict, customer_id: int = None, lead_id: int = None, source: str = "", stage: str = "", reply: str = "") -> None:
        competitor = ""
        for w in COMPARE_WORDS:
            if w in (summary.get("core_concern") or "") or w in (summary.get("selection_criteria") or ""):
                competitor = w
                break
        with session_scope() as session:
            session.add(ConversationMetric(
                session_id=summary.get("session_id") or "",
                customer_id=customer_id,
                lead_id=lead_id,
                source=source,
                stage=stage,
                sales_status=summary.get("sales_status") or "",
                core_concern=summary.get("core_concern") or "",
                competitor_mentioned=competitor,
                emotion="",
                has_next_step=bool(summary.get("next_goal")),
                gave_evidence=bool(summary.get("evidence_given")),
                bound_differentiator=bool(summary.get("selection_criteria")),
                is_deal=summary.get("sales_status") == "won",
            ))

    def _update_customer_status(self, customer_id: int, status: str) -> None:
        try:
            from core.sales_crm import crm
            crm.update_profile(customer_id, sales_status=status)
        except Exception as e:
            logger.debug("ConversationManager._update_customer_status 异常已忽略: %s", e)

    def list_summaries(self, session_id: str = "", status: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(ConversationSummary).order_by(ConversationSummary.id.desc())
            if session_id:
                query = query.where(ConversationSummary.session_id == session_id)
            if status:
                query = query.where(ConversationSummary.sales_status == status)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    def list_metrics(self, session_id: str = "", status: str = "", limit: int = 200) -> list[dict]:
        with session_scope() as session:
            query = select(ConversationMetric).order_by(ConversationMetric.id.desc())
            if session_id:
                query = query.where(ConversationMetric.session_id == session_id)
            if status:
                query = query.where(ConversationMetric.sales_status == status)
            return [_row_to_dict(r) for r in session.execute(query.limit(limit)).scalars().all()]

    def stats(self) -> dict:
        metrics = self.list_metrics(limit=100000)
        by_status = {}
        by_concern = {}
        total = len(metrics)
        for m in metrics:
            s = m.get("sales_status") or "new_lead"
            by_status[s] = by_status.get(s, 0) + 1
            c = m.get("core_concern") or "未识别"
            by_concern[c] = by_concern.get(c, 0) + 1
        return {
            "total": total,
            "has_next_step": sum(1 for m in metrics if m.get("has_next_step")),
            "gave_evidence": sum(1 for m in metrics if m.get("gave_evidence")),
            "deals": sum(1 for m in metrics if m.get("is_deal")),
            "by_status": by_status,
            "by_concern": by_concern,
            "next_step_rate": round(sum(1 for m in metrics if m.get("has_next_step")) / total * 100, 1) if total else 0.0,
            "evidence_rate": round(sum(1 for m in metrics if m.get("gave_evidence")) / total * 100, 1) if total else 0.0,
        }


conversation_manager = ConversationManager()
