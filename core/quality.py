"""会话质检与陪练：SOP 执行率、话术质量、绝对化承诺识别"""
from __future__ import annotations
import logging
import random

from sqlalchemy import select

from core.db import init_db, session_scope
from core.models import QualityReport
from core.sales_constants import STAGE_RANK

logger = logging.getLogger(__name__)

ABSOLUTE_WORDS = ["绝对", "百分百", "百分之百", "保证能", "肯定能", "一定能", "无效退款"]
HARD_SELL_WORDS = ["赶紧下单", "马上付款", "立即转账", "错过就没了"]


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class QualityChecker:
    def check_customer(
        self,
        customer_id: int = None,
        session_id: str = "",
    ) -> dict | None:
        try:
            from core.sales_crm import crm
        except Exception:
            return None
        customer = None
        chat_log = []
        if customer_id:
            customer = crm.get(customer_id)
        elif session_id:
            customer = crm.get_by_session(session_id)
        if not customer:
            return None
        chat_log = crm.get_chat_log(customer["id"], limit=50)
        report = self._analyze(customer, chat_log)
        init_db()
        with session_scope() as session:
            session.add(QualityReport(**report))
        return report

    def _analyze(self, customer: dict, chat_log: list[dict]) -> dict:
        issues = []
        samples = []
        absolute_hits = 0
        hard_sell_hits = 0
        long_replies = 0
        question_count = 0
        polite_count = 0
        reply_count = 0

        for item in chat_log:
            content = item.get("content") or ""
            role = item.get("role") or ""
            if role != "客服":
                continue
            reply_count += 1
            if "您" in content or "谢谢" in content:
                polite_count += 1
            if content.endswith("？") or content.endswith("?"):
                question_count += 1
            if len(content) > 200:
                long_replies += 1
            for word in ABSOLUTE_WORDS:
                if word in content:
                    absolute_hits += 1
                    issues.append(f"绝对化承诺：{word}")
                    samples.append(content[:120])
                    break
            for word in HARD_SELL_WORDS:
                if word in content:
                    hard_sell_hits += 1
                    issues.append(f"强逼单表达：{word}")
                    samples.append(content[:120])
                    break

        sop_score = max(0, 100 - absolute_hits * 20 - hard_sell_hits * 15)
        tone_score = 100
        if reply_count and polite_count / reply_count < 0.5:
            tone_score -= 15
            issues.append("礼貌用语覆盖率偏低")
        if reply_count and question_count / reply_count < 0.1:
            tone_score -= 10
            issues.append("提问比例偏低，容易变成单向输出")
        if long_replies:
            tone_score -= 5 * long_replies
            issues.append(f"存在 {long_replies} 条过长回复")

        score = max(0, min(100, round(sop_score * 0.6 + tone_score * 0.4)))
        return {
            "customer_id": customer.get("id"),
            "session_id": customer.get("session_id") or "",
            "score": score,
            "sop_score": max(0, sop_score),
            "tone_score": max(0, tone_score),
            "issues": "\n".join(issues[:20]),
            "samples": "\n---\n".join(samples[:5]),
            "created_at": _now(),
        }

    def list_reports(self, limit: int = 200) -> list[dict]:
        init_db()
        with session_scope() as session:
            rows = session.execute(
                select(QualityReport).order_by(QualityReport.id.desc()).limit(limit)
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def stats(self) -> dict:
        reports = self.list_reports(limit=100000)
        if not reports:
            return {"total": 0, "avg_score": 0, "issue_count": 0, "by_score": {}}
        avg = round(sum(r["score"] for r in reports) / len(reports), 1)
        issue_count = sum(1 for r in reports if r.get("issues"))
        buckets = {"优秀": 0, "良好": 0, "需改进": 0}
        for r in reports:
            if r["score"] >= 85:
                buckets["优秀"] += 1
            elif r["score"] >= 70:
                buckets["良好"] += 1
            else:
                buckets["需改进"] += 1
        return {"total": len(reports), "avg_score": avg, "issue_count": issue_count, "by_score": buckets}

    def scan_active_customers(self, limit: int = 20) -> int:
        try:
            from core.sales_crm import crm
            customers = crm.list_customers()
        except Exception:
            return 0
        count = 0
        for customer in customers:
            if STAGE_RANK.get(customer.get("stage") or "new", 0) < STAGE_RANK.get("recommended", 0):
                continue
            try:
                if self.check_customer(customer_id=customer["id"]):
                    count += 1
            except Exception as e:
                logger.error(f"客户 {customer.get('id')} 质检失败: {e}")
            if count >= limit:
                break
        return count

    def coach(self, stage: str = "异议处理", topic: str = "") -> str:
        """陪练：生成一条难缠客户消息，模拟真实销售场景"""
        fallback = {
            "异议处理": "你说是AI副业课，可我朋友学了三个月都没赚到钱，你这课凭什么值这个价？",
            "价格异议": "我看其他家才几百块，你们动不动就几千，太贵了，能不能便宜点？",
            "需求挖掘": "我就是随便问问，还没想好要不要学，你介绍一下吧。",
            "成交推进": "我再考虑一下，过几天再说吧。",
            "售后回访": "课程我买了，但每天太忙，根本没时间学，能退吗？",
        }
        try:
            from core.llm import create_llm
            llm = create_llm()
            prompt = (
                "你是一个难搞但确实有真实需求的客户，正在咨询AI副业课程。"
                f"当前场景：{stage}。请只说一句口语化的客户消息，不要解释，不要加前缀。"
                f"可围绕：{topic or '课程效果、价格、时间、同行对比、售后保障'}。"
            )
            reply = llm.invoke(prompt)
            text = reply.content if hasattr(reply, "content") else str(reply)
            return text.strip()[:200] or fallback.get(stage, fallback["异议处理"])
        except Exception as e:
            logger.warning(f"陪练 LLM 调用失败，使用模板: {e}")
            return random.choice([
                fallback.get(stage, fallback["异议处理"]),
                fallback["价格异议"] if stage != "价格异议" else fallback["异议处理"],
            ])


quality_checker = QualityChecker()
