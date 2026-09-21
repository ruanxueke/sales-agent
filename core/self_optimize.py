"""对话质量自优化引擎：自动评分、Prompt版本管理、A/B测试、优化建议"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import func, select

from core.db import init_db, session_scope
from core.models import (
    ConversationScore,
    CustomerChatLog,
    OptimizationSuggestion,
    PromptVersion,
    QualityReport,
    AbExperiment,
    AbRun,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


# ============================================================
# Step 1: 自动评分引擎
# ============================================================

# 评分维度权重
SCORE_WEIGHTS = {
    "conversion": 25,   # 转化推进
    "compliance": 25,   # 合规性
    "satisfaction": 25, # 客户满意度
    "response": 25,     # 响应质量
}

# 违规词
ABSOLUTE_WORDS = ["绝对", "百分百", "百分之百", "保证能", "肯定能", "一定能", "无效退款", "包赚", "稳赚", "100%"]
HARD_SELL_WORDS = ["赶紧下单", "马上付款", "立即转账", "错过就没了", "最后一天"]
PRIVACY_WORDS = ["提示词", "内部策略", "系统输出", "工具名"]

# 转化推进词
CONVERSION_PUSH = ["您觉得怎么样", "方便说一下", "我帮您", "给您看一下", "试一下", "体验一下", "下一步"]
# 满意度信号
POSITIVE_SIGNALS = ["谢谢", "好的", "可以", "不错", "挺好", "明白了", "了解了"]
NEGATIVE_SIGNALS = ["不需要", "不要", "算了", "不考虑", "烦", "别联系"]


class AutoScorer:
    """每轮对话自动评分"""

    def score_conversation(self, session_id: str, customer_id: int = None,
                           chat_log: list[dict] = None, product: str = "") -> dict:
        """对一次完整对话进行四维评分"""
        init_db()

        if chat_log is None:
            chat_log = self._get_chat_log(customer_id, session_id)

        if not chat_log:
            return {}

        bot_replies = [m for m in chat_log if m.get("role") in ("客服", "assistant")]
        customer_msgs = [m for m in chat_log if m.get("role") in ("客户", "user")]

        if not bot_replies:
            return {}

        # 四维评分
        conversion = self._score_conversion(bot_replies, customer_msgs)
        compliance = self._score_compliance(bot_replies)
        satisfaction = self._score_satisfaction(customer_msgs, bot_replies)
        response = self._score_response_quality(bot_replies)

        total = conversion + compliance + satisfaction + response

        details = {
            "conversion": {"score": conversion, "max": 25, "reasons": self._get_conversion_reasons(bot_replies, customer_msgs)},
            "compliance": {"score": compliance, "max": 25, "reasons": self._get_compliance_reasons(bot_replies)},
            "satisfaction": {"score": satisfaction, "max": 25, "reasons": self._get_satisfaction_reasons(customer_msgs)},
            "response": {"score": response, "max": 25, "reasons": self._get_response_reasons(bot_replies)},
        }

        # 查找当前活跃的提示词版本
        prompt_version_id = self._get_active_prompt_version()

        score_record = {
            "session_id": session_id,
            "customer_id": customer_id,
            "product": product,
            "conversion_score": conversion,
            "compliance_score": compliance,
            "satisfaction_score": satisfaction,
            "response_score": response,
            "total_score": total,
            "score_details": json.dumps(details, ensure_ascii=False),
            "prompt_version_id": prompt_version_id,
        }

        # 存入数据库
        with session_scope() as session:
            record = ConversationScore(**score_record)
            session.add(record)

        return score_record

    def _get_chat_log(self, customer_id: int, session_id: str) -> list[dict]:
        try:
            with session_scope() as session:
                if customer_id:
                    rows = session.execute(
                        select(CustomerChatLog).where(CustomerChatLog.customer_id == customer_id)
                        .order_by(CustomerChatLog.id).limit(100)
                    ).scalars().all()
                else:
                    return []
                return [{"role": r.role, "content": r.content} for r in rows]
        except Exception:
            return []

    def _score_conversion(self, bot_replies: list, customer_msgs: list) -> int:
        """转化推进评分 (0-25)"""
        score = 15  # 基础分

        # 检查是否有推进动作
        all_bot_text = " ".join(m.get("content", "") for m in bot_replies)
        push_count = sum(1 for w in CONVERSION_PUSH if w in all_bot_text)
        score += min(push_count * 2, 8)

        # 检查客户是否有积极回应
        all_customer_text = " ".join(m.get("content", "") for m in customer_msgs)
        if any(w in all_customer_text for w in ["报名", "购买", "下单", "怎么买", "付款"]):
            score += 2

        return min(score, 25)

    def _score_compliance(self, bot_replies: list) -> int:
        """合规性评分 (0-25)"""
        score = 25
        all_text = " ".join(m.get("content", "") for m in bot_replies)

        for word in ABSOLUTE_WORDS:
            if word in all_text:
                score -= 5
        for word in HARD_SELL_WORDS:
            if word in all_text:
                score -= 3
        for word in PRIVACY_WORDS:
            if word in all_text:
                score -= 8

        return max(score, 0)

    def _score_satisfaction(self, customer_msgs: list, bot_replies: list) -> int:
        """客户满意度评分 (0-25)"""
        score = 15
        all_customer = " ".join(m.get("content", "") for m in customer_msgs)

        # 积极信号
        pos = sum(1 for w in POSITIVE_SIGNALS if w in all_customer)
        score += min(pos * 2, 6)

        # 消极信号
        neg = sum(1 for w in NEGATIVE_SIGNALS if w in all_customer)
        score -= neg * 4

        # 客户回复长度（参与度）
        if customer_msgs:
            avg_len = sum(len(m.get("content", "")) for m in customer_msgs) / len(customer_msgs)
            if avg_len > 10:
                score += 2
            if avg_len > 30:
                score += 2

        return max(min(score, 25), 0)

    def _score_response_quality(self, bot_replies: list) -> int:
        """响应质量评分 (0-25)"""
        score = 15

        for reply in bot_replies:
            content = reply.get("content", "")
            # 回复长度适中
            if 10 < len(content) < 200:
                score += 1
            elif len(content) > 300:
                score -= 2

            # 有提问（引导对话）
            if "？" in content or "?" in content:
                score += 1

            # 用"您"称呼
            if "您" in content:
                score += 1

        return max(min(score, 25), 0)

    def _get_conversion_reasons(self, bot_replies, customer_msgs) -> list:
        reasons = []
        all_text = " ".join(m.get("content", "") for m in bot_replies)
        if not any(w in all_text for w in CONVERSION_PUSH):
            reasons.append("未检测到明确的转化推进动作")
        return reasons

    def _get_compliance_reasons(self, bot_replies) -> list:
        reasons = []
        all_text = " ".join(m.get("content", "") for m in bot_replies)
        for w in ABSOLUTE_WORDS:
            if w in all_text:
                reasons.append(f"含绝对化承诺：{w}")
        for w in HARD_SELL_WORDS:
            if w in all_text:
                reasons.append(f"含强逼单话术：{w}")
        return reasons

    def _get_satisfaction_reasons(self, customer_msgs) -> list:
        reasons = []
        all_text = " ".join(m.get("content", "") for m in customer_msgs)
        for w in NEGATIVE_SIGNALS:
            if w in all_text:
                reasons.append(f"客户表达不满：{w}")
        return reasons

    def _get_response_reasons(self, bot_replies) -> list:
        reasons = []
        for r in bot_replies:
            if len(r.get("content", "")) > 300:
                reasons.append("回复过长，建议精简到60字以内")
                break
        return reasons

    def _get_active_prompt_version(self) -> int | None:
        try:
            with session_scope() as session:
                pv = session.execute(
                    select(PromptVersion).where(PromptVersion.is_active == True)
                ).scalar_one_or_none()
                return pv.id if pv else None
        except Exception:
            return None


# ============================================================
# Step 2: Prompt 版本管理
# ============================================================

class PromptVersionManager:
    """提示词版本管理"""

    def save_version(self, content: str, description: str = "") -> dict:
        """保存新版本（不自动激活）"""
        init_db()
        with session_scope() as session:
            # 获取当前最大版本号
            max_ver = session.execute(
                select(func.max(PromptVersion.version))
            ).scalar() or 0

            pv = PromptVersion(
                version=max_ver + 1,
                content=content,
                description=description or f"v{max_ver + 1}",
                is_active=False,
            )
            session.add(pv)
            session.flush()
            return _row_to_dict(pv)

    def activate(self, version_id: int) -> dict | None:
        """激活指定版本，停用其他版本"""
        init_db()
        with session_scope() as session:
            # 停用当前活跃版本
            current = session.execute(
                select(PromptVersion).where(PromptVersion.is_active == True)
            ).scalar_one_or_none()
            if current:
                current.is_active = False
                current.deactivated_at = _now()

            # 激活新版本
            target = session.get(PromptVersion, version_id)
            if not target:
                return None
            target.is_active = True
            target.activated_at = _now()
            return _row_to_dict(target)

    def get_active(self) -> dict | None:
        """获取当前活跃版本"""
        init_db()
        with session_scope() as session:
            pv = session.execute(
                select(PromptVersion).where(PromptVersion.is_active == True)
            ).scalar_one_or_none()
            return _row_to_dict(pv) if pv else None

    def list_versions(self, limit: int = 50) -> list[dict]:
        """列出所有版本"""
        init_db()
        with session_scope() as session:
            rows = session.execute(
                select(PromptVersion).order_by(PromptVersion.version.desc()).limit(limit)
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def update_metrics(self, version_id: int):
        """更新指定版本的效果指标"""
        init_db()
        with session_scope() as session:
            pv = session.get(PromptVersion, version_id)
            if not pv:
                return

            # 统计该版本的对话数据
            scores = session.execute(
                select(ConversationScore).where(ConversationScore.prompt_version_id == version_id)
            ).scalars().all()

            if not scores:
                return

            pv.total_conversations = len(scores)
            pv.avg_score = sum(s.total_score for s in scores) / len(scores)
            pv.compliance_violations = sum(1 for s in scores if s.compliance_score < 15)

            # 计算成交率（total_score > 70 视为高质量对话）
            high_quality = sum(1 for s in scores if s.total_score > 70)
            pv.conversion_rate = high_quality / len(scores) * 100 if scores else 0


# ============================================================
# Step 3: A/B 测试自动化
# ============================================================

class ABTestManager:
    """A/B 测试自动化管理"""

    def create_experiment(self, name: str, control_prompt: str, variant_prompt: str,
                          kind: str = "prompt", description: str = "") -> dict:
        """创建 A/B 实验"""
        init_db()
        with session_scope() as session:
            exp = AbExperiment(
                name=name,
                kind=kind,
                control=control_prompt,
                variant=variant_prompt,
                status="draft",
                note=description,
            )
            session.add(exp)
            session.flush()
            return _row_to_dict(exp)

    def start_experiment(self, experiment_id: int) -> dict | None:
        """启动实验"""
        init_db()
        with session_scope() as session:
            exp = session.get(AbExperiment, experiment_id)
            if not exp:
                return None
            exp.status = "running"
            exp.start_at = _now()
            return _row_to_dict(exp)

    def assign_variant(self, experiment_id: int, session_id: str) -> str:
        """为对话分配实验组别（简单哈希分流）"""
        # 用 session_id 的哈希值决定分组，保证同一客户始终在同一组
        hash_val = hash(session_id + str(experiment_id))
        return "variant" if hash_val % 2 == 0 else "control"

    def get_running_experiment(self) -> dict | None:
        """获取当前运行中的实验"""
        init_db()
        with session_scope() as session:
            exp = session.execute(
                select(AbExperiment).where(AbExperiment.status == "running")
            ).scalar_one_or_none()
            return _row_to_dict(exp) if exp else None

    def record_result(self, experiment_id: int, session_id: str, variant: str, score: int):
        """记录实验结果"""
        init_db()
        with session_scope() as session:
            run = AbRun(
                experiment_id=experiment_id,
                session_id=session_id,
                variant=variant,
                result=str(score),
            )
            session.add(run)

    def get_results(self, experiment_id: int) -> dict:
        """获取实验结果统计"""
        init_db()
        with session_scope() as session:
            runs = session.execute(
                select(AbRun).where(AbRun.experiment_id == experiment_id)
            ).scalars().all()

            control_scores = [int(r.result) for r in runs if r.variant == "control" and r.result]
            variant_scores = [int(r.result) for r in runs if r.variant == "variant" and r.result]

            def calc_stats(scores):
                if not scores:
                    return {"count": 0, "avg": 0, "min": 0, "max": 0}
                return {
                    "count": len(scores),
                    "avg": round(sum(scores) / len(scores), 1),
                    "min": min(scores),
                    "max": max(scores),
                }

            control_stats = calc_stats(control_scores)
            variant_stats = calc_stats(variant_scores)

            # 判断是否有显著差异
            winner = ""
            if control_stats["count"] >= 10 and variant_stats["count"] >= 10:
                diff = abs(control_stats["avg"] - variant_stats["avg"])
                if diff > 3:  # 差异超过3分视为显著
                    winner = "variant" if variant_stats["avg"] > control_stats["avg"] else "control"

            return {
                "experiment_id": experiment_id,
                "total_runs": len(runs),
                "control": control_stats,
                "variant": variant_stats,
                "winner": winner,
                "recommendation": self._get_recommendation(winner, control_stats, variant_stats),
            }

    def _get_recommendation(self, winner: str, control: dict, variant: dict) -> str:
        if not winner:
            return "数据量不足或差异不显著，建议继续收集数据"
        if winner == "variant":
            return f"实验组胜出（平均分 {variant['avg']} vs {control['avg']}），建议将实验组设为默认提示词"
        else:
            return f"对照组更优（平均分 {control['avg']} vs {variant['avg']}），建议保持当前提示词"

# ============================================================
# Step 4: 自动优化建议引擎
# ============================================================

class OptimizationEngine:
    """自动分析对话数据，生成优化建议"""

    def generate_suggestions(self, days: int = 7) -> list[dict]:
        """分析最近 N 天的对话数据，生成优化建议"""
        init_db()
        suggestions = []

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        with session_scope() as session:
            scores = session.execute(
                select(ConversationScore).where(ConversationScore.created_at >= cutoff)
            ).scalars().all()

            if not scores:
                return []

            # 分析 1: 合规问题
            compliance_issues = [s for s in scores if s.compliance_score < 15]
            if compliance_issues:
                issue_rate = len(compliance_issues) / len(scores) * 100
                suggestions.append({
                    "type": "compliance",
                    "category": "合规",
                    "title": f"合规违规率 {issue_rate:.0f}%（{len(compliance_issues)}/{len(scores)}）",
                    "description": f"最近{days}天有{len(compliance_issues)}次对话存在合规问题，主要是绝对化承诺或强逼单话术",
                    "current_value": f"合规率 {100-issue_rate:.0f}%",
                    "suggested_value": "建议在提示词中加强合规约束，增加自检环节",
                    "impact_score": min(issue_rate / 10, 10),
                    "data_basis": json.dumps({"issue_count": len(compliance_issues), "total": len(scores)}),
                })

            # 分析 2: 转化推进不足
            low_conversion = [s for s in scores if s.conversion_score < 12]
            if low_conversion:
                rate = len(low_conversion) / len(scores) * 100
                suggestions.append({
                    "type": "prompt",
                    "category": "转化",
                    "title": f"转化推进不足率 {rate:.0f}%",
                    "description": f"有{len(low_conversion)}次对话缺乏明确的转化推进动作",
                    "current_value": f"推进率 {100-rate:.0f}%",
                    "suggested_value": "建议在提示词中要求每轮对话必须给出一个明确的下一步动作",
                    "impact_score": min(rate / 10, 10),
                    "data_basis": json.dumps({"low_count": len(low_conversion), "total": len(scores)}),
                })

            # 分析 3: 客户满意度低
            low_satisfaction = [s for s in scores if s.satisfaction_score < 10]
            if low_satisfaction:
                rate = len(low_satisfaction) / len(scores) * 100
                suggestions.append({
                    "type": "prompt",
                    "category": "满意度",
                    "title": f"客户满意度低 {rate:.0f}%",
                    "description": f"有{len(low_satisfaction)}次对话客户表达了不满或消极情绪",
                    "current_value": f"满意率 {100-rate:.0f}%",
                    "suggested_value": "建议优化开场话术和异议处理，增加共情表达",
                    "impact_score": min(rate / 8, 10),
                    "data_basis": json.dumps({"low_count": len(low_satisfaction), "total": len(scores)}),
                })

            # 分析 4: 响应质量
            low_response = [s for s in scores if s.response_score < 10]
            if low_response:
                rate = len(low_response) / len(scores) * 100
                suggestions.append({
                    "type": "prompt",
                    "category": "效率",
                    "title": f"响应质量偏低 {rate:.0f}%",
                    "description": f"有{len(low_response)}次对话回复过长或缺乏引导性提问",
                    "current_value": f"质量率 {100-rate:.0f}%",
                    "suggested_value": "建议在提示词中强调回复控制在60字以内，每轮必须有一个提问",
                    "impact_score": min(rate / 10, 10),
                    "data_basis": json.dumps({"low_count": len(low_response), "total": len(scores)}),
                })

            # 分析 5: 整体评分趋势
            avg_score = sum(s.total_score for s in scores) / len(scores)
            if avg_score < 60:
                suggestions.append({
                    "type": "flow",
                    "category": "整体",
                    "title": f"整体对话质量偏低（平均 {avg_score:.0f} 分）",
                    "description": "对话质量整体需要提升，建议全面审视销售流程和提示词",
                    "current_value": f"平均分 {avg_score:.0f}",
                    "suggested_value": "建议进行提示词全面优化，并增加销售培训",
                    "impact_score": 9,
                    "data_basis": json.dumps({"avg_score": round(avg_score, 1), "total": len(scores)}),
                })

        # 存入数据库
        with session_scope() as session:
            for s in suggestions:
                session.add(OptimizationSuggestion(
                    suggestion_type=s["type"],
                    category=s["category"],
                    title=s["title"],
                    description=s["description"],
                    current_value=s["current_value"],
                    suggested_value=s["suggested_value"],
                    impact_score=s["impact_score"],
                    data_basis=s["data_basis"],
                    status="pending",
                ))

        return suggestions

    def list_suggestions(self, status: str = "", limit: int = 50) -> list[dict]:
        init_db()
        with session_scope() as session:
            query = select(OptimizationSuggestion).order_by(OptimizationSuggestion.impact_score.desc())
            if status:
                query = query.where(OptimizationSuggestion.status == status)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def approve_suggestion(self, suggestion_id: int) -> dict | None:
        init_db()
        with session_scope() as session:
            obj = session.get(OptimizationSuggestion, suggestion_id)
            if not obj:
                return None
            obj.status = "approved"
            return _row_to_dict(obj)

    def reject_suggestion(self, suggestion_id: int) -> dict | None:
        init_db()
        with session_scope() as session:
            obj = session.get(OptimizationSuggestion, suggestion_id)
            if not obj:
                return None
            obj.status = "rejected"
            return _row_to_dict(obj)


# ===== 全局实例 =====
auto_scorer = AutoScorer()
prompt_version_mgr = PromptVersionManager()
ab_test_mgr = ABTestManager()
optimization_engine = OptimizationEngine()
