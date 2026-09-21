"""销售客服 Agent（纯 LLM 版 + 弹药库/合规/结构化摘要）"""
from __future__ import annotations
import logging
import threading
import time
from pathlib import Path

from langchain_classic.prompts import PromptTemplate
from config.settings import settings
from core.cache import semantic_cache
from core.concurrency import rate_limiter
from core.llm import create_llm
from core.memory import memory_manager
from core.sales_crm import crm
from core.sales_extract import (
    build_profile_text,
    compute_intent_level,
    compute_stage,
    detect_customer_product,
    extract_profile,
)
from core.tenancy import tenant_from_session_id
from core.usage import usage_recorder

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).resolve().parent.parent / "config" / "sales_prompt.txt"

SYSTEM_PROMPT = """你是一位专业的 AI 课程销售顾问，负责销售全流程：获客、需求挖掘、推荐、报价、转化、跟进。

参考知识库信息：
{context}

当前客户档案：
{customer_profile}

当前销售阶段：{stage}
阶段说明：
- new：开场破冰，了解客户是谁、有什么需求
- understanding：继续挖掘身份（个人/企业）、基础（零基础/有基础）、目标、预算
- recommended：根据客户需求推荐匹配课程
- high_intent：重点介绍价格、优惠、报名方式，引导留联系方式或报名
- enrolled：确认报名课程、姓名、联系方式，告知后续安排
- won / after_sales / lost：成交、售后、流失维护

历史对话：
{chat_history}

客户：{input}
销售原则：先需求后推荐，不硬推销；信息不足时自然追问；客户问价格或优惠时如实按知识库回答，并引导留联系方式；客户表达报名意向后，确认课程、姓名和联系方式。请优先依据知识库信息回答，给出专业、友好、简洁的回答："""


def load_system_prompt() -> str:
    """读取可编辑的销售提示词文件，缺失时使用内置默认提示词"""
    try:
        return PROMPT_FILE.read_text(encoding="utf-8").strip()
    except OSError as e:
        logger.warning("销售提示词文件读取失败，使用默认提示词: %s", e)
        return SYSTEM_PROMPT


class SalesAgent:
    def __init__(self):
        self._llm = None
        self._llm_key = ""
        self._llm_lock = threading.Lock()

    def _ensure_channel_lead(
        self,
        session_id: str,
        nickname: str,
        source: str,
        tenant_id: int | None = None,
    ) -> None:
        """首次对话先沉淀为线索，L3 后再关联正式客户。"""
        if not session_id:
            return
        try:
            from core.lead import lead_manager

            lead_manager.upsert_from_channel(
                session_id=session_id,
                source=source or "wechat",
                nickname=nickname or "",
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning("线索自动沉淀失败: %s", e)

    def _sync_lead_customer(self, customer: dict, source: str) -> None:
        """达到 L3 建档后，将原线索升级并关联正式客户。"""
        if not customer:
            return
        try:
            from core.lead import lead_manager

            lead_manager.upsert_from_customer(customer, source=source or "wechat")
        except Exception as e:
            logger.warning("线索升级客户失败: %s", e)

    def _get_llm(self):
        """按 llm_router 当前生效的模型取 LLM，并在模型切换时重建。

        原来这里只判断 `self._llm is None` 就永久缓存，于是 llm_router 的主备切换和
        `/system/llm/switch` 对已存在的 Agent 对象**完全无效**——路由算出来该用备用，
        实际发出去的还是主模型。所以缓存键必须带上"当前生效模型"。
        """
        from core.llm_router import llm_router
        want = llm_router.active_model()
        if self._llm is not None and self._llm_key == want:
            return self._llm
        with self._llm_lock:
            if self._llm is None or self._llm_key != want:
                self._llm = llm_router.get()
                self._llm_key = want
        return self._llm

    def _retrieve_context(self, message: str, tenant_id: int = 0):
        try:
            from core.rag import rag_engine
            docs = rag_engine.query_with_scores(
                message,
                k=settings.RAG_TOP_K,
                tenant_id=tenant_id,
            )
            threshold = settings.RAG_SCORE_THRESHOLD
            chosen = [(doc, score) for doc, score in docs if score >= threshold]
            sources = [
                {
                    "source": doc.metadata.get("source_filename") or doc.metadata.get("source") or "知识库",
                    "score": round(score, 3),
                    "snippet": (doc.page_content or "")[:80],
                }
                for doc, score in chosen
            ]
            return "\n\n".join(doc.page_content for doc, _ in chosen), sources
        except Exception as e:
            logger.warning(f"知识库检索失败，使用纯 LLM 回答: {e}")
            return "", []

    def _retrieve_ammo_context(self, message: str, sales_status: str = "") -> str:
        """弹药库与赢单上下文，作为知识检索的补充，不改主回复链路"""
        parts = []
        try:
            from core.ammo import ammo_manager
            ammo = ammo_manager.retrieve_context(message, sales_status=sales_status)
            if ammo:
                parts.append(ammo)
        except Exception as e:
            logger.warning(f"弹药库检索失败: {e}")
        try:
            from core.winning import winning_manager
            if winning_manager.is_winning_scene(message):
                win = winning_manager.retrieve_context(message)
                if win:
                    parts.append(win)
        except Exception as e:
            logger.warning(f"赢单上下文检索失败: {e}")
        return "\n\n".join(parts)

    def _after_reply(self, customer, created_now, pre_history, message, reply_text):
        """回复后：补存聊天记录、结构化摘要，首次达到 L3 时发送销售通知"""
        tenant_id = int((customer or {}).get("tenant_id") or 0)
        try:
            from core.conversation import conversation_manager
            conversation_manager.record(
                message,
                reply_text,
                (customer or {}).get("session_id") or "",
                customer=customer,
                source=(customer or {}).get("source") or "wechat",
            )
        except Exception as e:
            logger.warning(f"会话结构化摘要记录失败: {e}")
        if customer is None:
            return
        if created_now:
            from datetime import datetime, timedelta
            if not customer.get("next_follow_up"):
                crm.update_profile(
                    customer["id"],
                    tenant_id=tenant_id,
                    next_follow_up=(datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                )
            for h in pre_history:
                crm.append_chat(
                    customer["id"],
                    "客户",
                    h.get("input", ""),
                    tenant_id=tenant_id,
                )
                crm.append_chat(
                    customer["id"],
                    "客服",
                    h.get("output", ""),
                    tenant_id=tenant_id,
                )
        crm.append_chat(
            customer["id"],
            "客户",
            message,
            tenant_id=tenant_id,
        )
        crm.append_chat(
            customer["id"],
            "客服",
            reply_text,
            tenant_id=tenant_id,
        )
        if created_now:
            from core.notify import notify_sales
            try:
                notify_sales(
                    customer,
                    crm.get_chat_log(
                        customer["id"],
                        limit=30,
                        tenant_id=tenant_id,
                    ),
                )
            except Exception as e:
                logger.error(f"销售线索通知失败: {e}")

        # 自动评分（异步，不阻塞回复）
        try:
            from core.tasks import send_task
            send_task("score_conversation", kwargs={
                "session_id": (customer or {}).get("session_id") or "",
                "customer_id": (customer or {}).get("id"),
                "product": (customer or {}).get("product") or "",
            })
        except Exception as e:
            logger.warning(f"Auto scoring failed: {e}")

    def chat(self, message: str, session_id: str = "default", nickname: str = None, source: str = "wechat") -> str:
        product_key = ""  # 产品标识，默认为空
        try:
            if not rate_limiter.check_user(session_id):
                return "您咨询得有点快，请稍等几秒再继续。"
        except Exception as e:
            logger.warning(f"限流检查失败: {e}")

        try:
            from core.security_layers import blocklist_manager, security_layers
        except Exception:
            blocklist_manager = None
            security_layers = None

        try:
            if blocklist_manager and blocklist_manager.is_blocked(session_id):
                return "抱歉，暂时无法为您服务。如需帮助请联系人工客服。"
        except Exception as e:
            logger.warning(f"黑名单检查失败: {e}")

        try:
            if security_layers and security_layers.detect_injection(message):
                logger.warning("检测到提示词注入尝试 session=%s", session_id)
                return "抱歉，我只能回答与课程相关的问题哦～"
        except Exception as e:
            logger.warning(f"注入检查失败: {e}")

        tenant_id = tenant_from_session_id(session_id)
        self._ensure_channel_lead(
            session_id,
            nickname or "",
            source,
            tenant_id=tenant_id,
        )

        safe_message = message
        try:
            if security_layers:
                safe_message = security_layers.mask_sensitive(message)
        except Exception as e:
            logger.warning(f"敏感信息脱敏失败: {e}")

        compliance_hit = None
        try:
            from core.compliance import compliance_manager
            compliance_hit = compliance_manager.check(
                message,
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning(f"合规检查失败: {e}")

        if settings.HANDOVER_ENABLED:
            from core.handover_words import contains_handover_keyword
            if contains_handover_keyword(message, source):
                try:
                    from core.handover import handover_manager
                    handover_manager.request(
                        session_id=session_id,
                        source=source,
                        nickname=nickname or "",
                        reason=message[:100],
                    )
                except Exception as e:
                    logger.error(f"转人工记录失败: {e}")
                return "好的，您说的这个比较重要，我帮您联系专人处理，请您稍等。"
            if compliance_hit and compliance_hit.get("action") == "handover":
                try:
                    from core.handover import handover_manager
                    handover_manager.request(
                        session_id=session_id,
                        source=source,
                        nickname=nickname or "",
                        reason=f"[合规]{compliance_hit.get('description') or ''}: {message[:80]}",
                    )
                except Exception as e:
                    logger.error(f"合规转人工失败: {e}")
                return "好的，您说的这个涉及合规，我帮您联系专业老师处理，请您稍等。"
            if compliance_hit and compliance_hit.get("action") == "stop":
                customer_stop = crm.get_by_session(session_id, tenant_id=tenant_id)
                if customer_stop:
                    try:
                        crm.update_profile(
                            customer_stop["id"],
                            tenant_id=tenant_id,
                            sales_status="rejected",
                            notes=(customer_stop.get("notes") or "") + "\n[合规] 客户明确拒绝，停止触达",
                        )
                    except Exception as e:
                        logger.warning(f"停止触达记录失败: {e}")
                return "好的，尊重您的选择，就不打扰您了。以后有需要随时找我。"
        paid_words = (
            "付款成功", "支付成功", "已支付", "已付款", "打款了",
            "我付了", "我付款了", "付了", "我已经付了", "支付了", "付款成功",
        )
        if any(word in message for word in paid_words):
            reply = "好的，那您先忙，我帮您核实一下付款状态，请您稍等。"
            try:
                customer = crm.get_by_session(session_id, tenant_id=tenant_id)
                if customer:
                    crm.create_notification(
                        customer["id"],
                        tenant_id=tenant_id,
                        target="付款核实",
                        content=f"客户提示已付款，请核实交付。{message[:100]}",
                        status="pending",
                    )
            except Exception as e:
                logger.warning(f"付款核实通知失败: {e}")
            try:
                memory_manager.get_or_create(session_id).save_context(message, reply)
            except Exception as e:
                logger.warning(f"付款核实对话记录失败: {e}")
            return reply
        extracted = extract_profile(message)
        prospective_stage = compute_stage({"stage": "new"}, extracted)
        new_intent_level = compute_intent_level(prospective_stage, extracted["intent_score"])
        reached_l3 = new_intent_level.startswith(("L3", "L4", "L5"))

        memory = memory_manager.get_or_create(session_id)
        pre_history = []
        try:
            pre_history = memory.load_history(limit=30)
        except Exception as e:
            logger.debug("SalesAgent.chat 异常已忽略: %s", e)

        customer = crm.get_by_session(session_id, tenant_id=tenant_id)
        created_now = False
        if customer is None and reached_l3:
            customer = crm.get_or_create(
                session_id,
                nickname=nickname or "",
                source=source,
                tenant_id=tenant_id,
            )
            created_now = True
            try:
                from core.compliance_flow import compliance_flow
                compliance_flow.add_consent(
                    session_id,
                    source=source,
                    content="进入销售对话授权",
                    tenant_id=tenant_id,
                )
            except Exception as e:
                logger.debug("SalesAgent.chat 异常已忽略: %s", e)

        merged = dict(extracted)
        if created_now:
            for h in pre_history:
                old = extract_profile(h.get("input", ""))
                for key in ("name", "phone", "wechat_id", "identity", "level", "goal", "budget", "interest"):
                    if not merged.get(key) and old.get(key):
                        merged[key] = old[key]
                merged["intent_score"] = max(merged["intent_score"], old["intent_score"])

        if customer is not None:
            updates = {
                "name": merged["name"],
                "phone": merged["phone"],
                "wechat_id": merged["wechat_id"],
                "identity": merged["identity"],
                "level": merged["level"],
                "goal": merged["goal"],
                "budget": merged["budget"],
                "interest": merged["interest"],
                "intent_score": max(customer.get("intent_score") or 0, merged["intent_score"]),
            }
            crm.update_profile(
                customer["id"],
                tenant_id=tenant_id,
                **{k: v for k, v in updates.items() if v},
            )
            new_stage = compute_stage(customer, extracted)
            crm.advance_stage(
                customer["id"],
                new_stage,
                trigger=message[:50],
                tenant_id=tenant_id,
            )
            customer = crm.get(customer["id"], tenant_id=tenant_id)
            intent_level = compute_intent_level(
                customer.get("stage") or "new",
                customer.get("intent_score") or 0,
            )
            if customer.get("intent_level") != intent_level:
                crm.update_profile(
                    customer["id"],
                    tenant_id=tenant_id,
                    intent_level=intent_level,
                )
            customer = crm.get(customer["id"], tenant_id=tenant_id)
            profile_text = build_profile_text(customer)
            stage = customer.get("stage") or "new"
            # 产品识别
            detected_product = detect_customer_product(message, customer.get("source") or "")
            product_key = customer.get("product") or detected_product or ""
            if detected_product and not customer.get("product"):
                try:
                    crm.update_profile(
                        customer["id"],
                        tenant_id=tenant_id,
                        product=detected_product,
                    )
                    customer["product"] = detected_product
                    product_key = detected_product
                except Exception as prod_err:
                    logger.warning(f"产品标记保存失败: {prod_err}")
            self._sync_lead_customer(customer, source)
        else:
            # 新客户产品识别
            detected_product = detect_customer_product(message, "")
            product_key = detected_product or ""
            profile_text = build_profile_text({"intent_level": new_intent_level})
            stage = prospective_stage

        cache_scope = "|".join([
            message,
            stage,
            merged.get("identity") or "",
            merged.get("level") or "",
            merged.get("goal") or "",
            merged.get("interest") or "",
            merged.get("budget") or "",
            str(merged.get("intent_score") or 0),
        ])
        try:
            cache_scope = f"{tenant_id}|{cache_scope}"
            cached_reply = semantic_cache.get(cache_scope)
        except Exception as e:
            cached_reply = None
            logger.warning(f"语义缓存读取失败: {e}")
        if cached_reply:
            memory.save_context(message, cached_reply)
            self._after_reply(customer, created_now, pre_history, message, cached_reply)
            return cached_reply

        chat_history = ""
        try:
            chat_history = memory.get_summary(limit=6)
        except Exception as e:
            logger.debug("SalesAgent.chat 异常已忽略: %s", e)

        context, sources = self._retrieve_context(message, tenant_id=tenant_id)
        ammo_context = self._retrieve_ammo_context(message, sales_status=(customer or {}).get("sales_status") or "")
        if ammo_context:
            context = (context + "\n\n" + ammo_context).strip()
        tool_calls = []
        try:
            from core.tools import run_tools
            tool_calls = run_tools(message, (customer or {}).get("session_id") or session_id)
            if tool_calls:
                tool_text = "\n".join(f"[{c['tool']}] {c['result']}" for c in tool_calls)
                context = (context + "\n\n【工具结果】\n" + tool_text).strip()
        except Exception as e:
            logger.warning(f"工具调用失败: {e}")

        try:
            prompt = PromptTemplate(
                template=load_system_prompt(),
                input_variables=["context", "customer_profile", "stage", "chat_history", "input", "product"],
            )
        except Exception as e:
            logger.error(f"销售提示词文件格式有误，使用默认提示词: {e}")
            prompt = PromptTemplate(
                template=SYSTEM_PROMPT,
                input_variables=["context", "customer_profile", "stage", "chat_history", "input", "product"],
            )

        reply_text = ""
        last_error = None
        used_model = settings.LLM_MODEL
        used_tokens = {}
        llm = self._get_llm()
        chain = prompt | llm
        call_start = time.time()
        from core.llm_router import llm_router
        for attempt in range(3):
            try:
                reply = chain.invoke({
                    "context": context or "（无）",
                    "customer_profile": profile_text,
                    "stage": stage,
                    "chat_history": chat_history or "（新对话）",
                    "input": message,
                    "product": product_key,
                })
                reply_text = reply.content if hasattr(reply, 'content') else str(reply)
                llm_router.record_success()
                try:
                    meta = getattr(reply, "response_metadata", None) or {}
                    used_tokens = meta.get("token_usage") or {}
                    usage_recorder.record(
                        session_id, source, used_model, used_tokens,
                        int((time.time() - call_start) * 1000),
                    )
                except Exception as usage_err:
                    logger.warning(f"LLM 用量统计失败: {usage_err}")
                break
            except Exception as e:
                last_error = e
                llm_router.record_failure()
                logger.error(f"LLM 调用失败(第{attempt + 1}次): {e}")
                if attempt < 2:
                    time.sleep(1 + attempt)
        if not reply_text:
            logger.error(f"LLM 最终调用失败: {last_error}")
            try:
                backup_llm = llm_router.backup()
                if backup_llm is not None:
                    used_model = settings.BACKUP_LLM_MODEL or "qwen-plus"
                    backup_chain = prompt | backup_llm
                    reply = backup_chain.invoke({
                        "context": context or "（无）",
                        "customer_profile": profile_text,
                        "stage": stage,
                        "chat_history": chat_history or "（新对话）",
                        "input": message,
                      "product": product_key,
                    })
                    reply_text = reply.content if hasattr(reply, 'content') else str(reply)
                    used_tokens = (getattr(reply, "response_metadata", None) or {}).get("token_usage") or {}
                    logger.info("主模型失败，已切换备用模型")
            except Exception as backup_err:
                logger.error(f"备用模型调用失败: {backup_err}")
            if not reply_text:
                reply_text = "抱歉，我暂时无法处理您的问题，请稍后再试。"

        try:
            if security_layers and security_layers.moderate_reply(reply_text):
                reply_text = security_layers.moderate_reply(reply_text)
        except Exception as e:
            logger.warning(f"回复审核失败: {e}")

        latency_ms = int((time.time() - call_start) * 1000)
        try:
            from core.llm_trace import llm_trace_manager
            llm_trace_manager.add(
                session_id=session_id, model=used_model, message=safe_message, reply=reply_text,
                prompt_tokens=used_tokens.get("prompt_tokens") or used_tokens.get("prompt_tokens", 0),
                completion_tokens=used_tokens.get("completion_tokens") or 0,
                latency_ms=latency_ms,
            )
            if latency_ms > getattr(settings, "LLM_SLOW_MS", 30000):
                try:
                    customer_obj = crm.get_by_session(session_id)
                    if customer_obj:
                        crm.create_notification(customer_obj["id"], target="AI慢响应", content=f"回复耗时{latency_ms}ms", status="pending")
                except Exception as notify_err:
                    logger.warning(f"慢响应通知失败: {notify_err}")
        except Exception as e:
            logger.warning(f"LLM 追踪记录失败: {e}")

        try:
            from core.knowledge_gaps import knowledge_gap_manager
            if not sources:
                knowledge_gap_manager.add(session_id, safe_message)
        except Exception as e:
            logger.warning(f"知识缺口收集失败: {e}")

        try:
            if any(w in message for w in ("不满意", "敷衍", "垃圾", "听不懂", "答非所问")):
                from core.feedback import feedback_manager
                feedback_manager.add(session_id=session_id, message=safe_message, reply=reply_text, rating="bad", issue_type="客户不满意")
        except Exception as e:
            logger.warning(f"活体反馈采集失败: {e}")

        try:
            from core.citations import citation_manager
            trace = list(sources or [])
            for c in tool_calls:
                trace.append({"type": "tool", "tool": c["tool"], "result": c["result"][:200]})
            if trace:
                citation_manager.add(session_id, safe_message, reply_text, trace)
        except Exception as e:
            logger.warning(f"引用记录保存失败: {e}")

        try:
            semantic_cache.set(cache_scope, reply_text)
        except Exception as e:
            logger.warning(f"语义缓存写入失败: {e}")

        memory.save_context(message, reply_text)
        self._after_reply(customer, created_now, pre_history, safe_message, reply_text)
        return reply_text


sales_agent = SalesAgent()
