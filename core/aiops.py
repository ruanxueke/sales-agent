"""AI 主动经营：每日简报、赢单教练、合同风险、自然语言问数"""
from __future__ import annotations
import json
import logging
from datetime import datetime

from core.db import init_db, session_scope
from core.models import AiReport

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _invoke_llm(prompt: str, fallback: str, report_type: str = "aiops", scope: str = "") -> str:
    try:
        from core.llm import create_llm
        llm = create_llm()
        reply = llm.invoke(prompt)
        text = reply.content if hasattr(reply, "content") else str(reply)
        result = text.strip() or fallback
    except Exception as e:
        logger.warning(f"AI经营 LLM 调用失败，使用模板: {e}")
        result = fallback
    try:
        from core.usage import usage_recorder
        usage_recorder.record("aiops", "aiops", "deepseek", {}, 0)
    except Exception as e:
        logger.debug("_invoke_llm 异常已忽略: %s", e)
    try:
        init_db()
        with session_scope() as session:
            session.add(AiReport(
                report_type=report_type,
                scope=scope or "",
                content=result,
                meta=json.dumps({"prompt": prompt[:500]}, ensure_ascii=False),
            ))
    except Exception as e:
        logger.error(f"AI报告落库失败: {e}")
    return result


class AiOpsManager:
    def daily_briefing(self) -> dict:
        data = self._collect()
        lines = [
            "今日销售经营简报",
            f"- 客户总数 {data['customers']}，线索 {data['leads']}，高意向/已成交 {data['high_intent']}",
            f"- 商机 {data['opportunities']} 个，管道金额 {data['pipeline']} 元，停滞商机 {data['stale_opportunities']} 个",
            f"- 成交订单 {data['orders']}，回款 {data['received']} 元，应收 {data['outstanding']} 元，逾期 {data['overdue']} 元",
            f"- 待跟进 {data['pending_followups']}，待处理工单 {data['open_tickets']}，逾期工单 {data['overdue_tickets']}",
            f"- 待审批 {data['approvals_pending']}，复购待触达 {data['repurchases_pending']}",
            "建议：优先处理逾期回款与停滞商机，再安排高意向客户的报价和跟进。",
        ]
        fallback = "\n".join(lines)
        prompt = (
            "你是销售运营负责人，请基于以下经营数据生成一段不超过200字的中文每日经营简报，"
            "给出最重要的3条行动建议，不要使用 Markdown。\n"
            + json.dumps(data, ensure_ascii=False)
        )
        content = _invoke_llm(prompt, fallback, "daily_briefing")
        return {"content": content, "data": data}

    def deal_coach(self, opportunity_id: int) -> dict | None:
        try:
            from core.opportunity import opportunity_manager
            opp = opportunity_manager.get(opportunity_id)
        except Exception:
            opp = None
        if not opp:
            return None
        stage = opp.get("stage") or "qualifying"
        advice_map = {
            "qualifying": "先补齐客户需求、预算、决策人和时间点，再进入方案报价。",
            "proposal": "把方案绑定到客户的具体痛点，主动约一次讲解或试用，减少只看价格。",
            "negotiation": "明确卡点：价格、风险还是时间。能给试用就给试用，能拆分期就拆分期。",
            "won": "尽快推动合同签署和回款，并安排交付与售后回访。",
            "lost": "记录输单原因，约定下一次触达时间，保持长期关系。",
        }
        fallback = (
            f"商机「{opp.get('name')}」当前处于 {stage}，金额 {opp.get('amount')} 元，"
            f"预测赢率 {opp.get('win_rate')}%，风险等级 {opp.get('risk_level')}。\n"
            + advice_map.get(stage, "推进下一步并记录客户反馈。")
        )
        prompt = (
            "你是销售教练，请针对以下商机给出3条具体可执行的推进建议，语气直接，不超过200字。\n"
            + json.dumps(opp, ensure_ascii=False)
        )
        content = _invoke_llm(prompt, fallback, "deal_coach", scope=f"opportunity:{opportunity_id}")
        return {"content": content, "opportunity": opp}

    def contract_risk(self, contract_id: int) -> dict | None:
        try:
            from core.cpq import cpq_manager
            contract = next((c for c in cpq_manager.list_contracts(limit=100000) if c.get("id") == contract_id), None)
        except Exception:
            contract = None
        if not contract:
            return None
        risks = []
        if float(contract.get("amount") or 0) <= 0:
            risks.append({"level": "high", "message": "合同金额缺失或为0"})
        if not (contract.get("terms") or "").strip():
            risks.append({"level": "medium", "message": "合同条款为空"})
        if contract.get("status") in ("draft", "approving", "approved") and not contract.get("signed_at"):
            risks.append({"level": "high", "message": "合同尚未签署"})
        if contract.get("expires_at") and contract["expires_at"] < _now():
            risks.append({"level": "high", "message": "合同已过期"})
        if not risks:
            risks.append({"level": "low", "message": "未发现明显风险"})
        fallback = "\n".join(f"- [{r['level']}] {r['message']}" for r in risks)
        prompt = (
            "你是企业法务风控，请审查以下合同数据，指出风险点并给出处理建议，不超过200字。\n"
            + json.dumps(contract, ensure_ascii=False)
        )
        content = _invoke_llm(prompt, fallback, "contract_risk", scope=f"contract:{contract_id}")
        return {"content": content, "risks": risks, "contract": contract}

    def ask_data(self, question: str) -> dict:
        data = self._collect()
        q = question or ""
        answer = "我可以回答客户、线索、商机、订单、回款、跟进、工单、营销和风险类数据问题。"
        if any(k in q for k in ("客户", "人数")):
            answer = f"当前客户总数 {data['customers']}，高意向/已成交 {data['high_intent']}。"
        elif any(k in q for k in ("线索", "公海")):
            answer = f"当前线索 {data['leads']} 条，公海 {data['ocean']} 条。"
        elif any(k in q for k in ("商机", "管道")):
            answer = f"当前商机 {data['opportunities']} 个，管道金额 {data['pipeline']} 元，停滞 {data['stale_opportunities']} 个。"
        elif any(k in q for k in ("订单", "成交", "收入")):
            answer = f"已成交订单 {data['orders']}，累计回款 {data['received']} 元。"
        elif any(k in q for k in ("回款", "应收", "逾期")):
            answer = f"应收 {data['outstanding']} 元，逾期 {data['overdue']} 元。"
        elif any(k in q for k in ("跟进",)):
            answer = f"当前待跟进 {data['pending_followups']} 条。"
        elif any(k in q for k in ("工单", "售后")):
            answer = f"待处理工单 {data['open_tickets']}，逾期工单 {data['overdue_tickets']}。"
        elif any(k in q for k in ("营销", "广告", "ROI")):
            answer = f"营销活动 {data['campaigns']} 个，广告ROI {data['ad_roi']}，复购待触达 {data['repurchases_pending']}。"
        elif any(k in q for k in ("风险", "预警")):
            answer = f"应收逾期 {data['overdue']} 元，逾期工单 {data['overdue_tickets']}，停滞商机 {data['stale_opportunities']}。"
        prompt = (
            "你是销售数据助手，请用一句简洁中文回答这个问题，不要编造数据：\n"
            f"问题：{q}\n数据：{json.dumps(data, ensure_ascii=False)}"
        )
        content = _invoke_llm(prompt, answer, "ask_data", scope=q[:200])
        return {"answer": content, "data": data}

    def list_reports(self, report_type: str = "", limit: int = 200) -> list[dict]:
        init_db()
        from sqlalchemy import select
        with session_scope() as session:
            query = select(AiReport).order_by(AiReport.id.desc())
            if report_type:
                query = query.where(AiReport.report_type == report_type)
            rows = session.execute(query.limit(limit)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    @staticmethod
    def _collect() -> dict:
        data = {
            "customers": 0, "leads": 0, "ocean": 0, "high_intent": 0, "won": 0,
            "opportunities": 0, "pipeline": 0, "stale_opportunities": 0,
            "orders": 0, "received": 0, "outstanding": 0, "overdue": 0,
            "pending_followups": 0, "open_tickets": 0, "overdue_tickets": 0,
            "approvals_pending": 0, "repurchases_pending": 0, "campaigns": 0,
            "ad_roi": 0,
        }
        try:
            from core.platform import platform_manager
            data.update(platform_manager.bi_metrics().get("kpis", {}))
        except Exception as e:
            logger.warning("经营看板 线索 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.marketing import marketing_manager
            mk = marketing_manager.stats()
            data["repurchases_pending"] = mk.get("repurchases_pending", 0)
            data["campaigns"] = mk.get("campaigns", 0)
            data["ad_roi"] = mk.get("roi", 0)
        except Exception as e:
            logger.warning("经营看板 营销 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.cpq import cpq_manager
            data["approvals_pending"] = cpq_manager.stats().get("approvals_pending", 0)
        except Exception as e:
            logger.warning("经营看板 报价合同 指标采集失败，该部分会显示为 0/空: %s", e)
        try:
            from core.finance import finance_manager
            fin = finance_manager.stats()
            data["received"] = fin.get("received", 0)
            data["outstanding"] = fin.get("outstanding", 0)
            data["overdue"] = fin.get("overdue", 0)
        except Exception as e:
            logger.warning("经营看板 财务 指标采集失败，该部分会显示为 0/空: %s", e)
        return data


aiops_manager = AiOpsManager()
