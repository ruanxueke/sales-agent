"""SQLAlchemy 数据模型：客户、阶段、聊天、通知"""
from __future__ import annotations
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, Integer, String, Text

from core.db import Base


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), unique=True, nullable=False, index=True)
    nickname = Column(String(128), default="")
    source = Column(String(32), default="wechat")
    display_id = Column(String(128), default="", index=True)
    name = Column(String(64), default="")
    phone = Column(String(32), default="")
    wechat_id = Column(String(128), default="")
    identity = Column(String(32), default="")
    level = Column(String(32), default="")
    goal = Column(String(64), default="")
    budget = Column(String(64), default="")
    interest = Column(String(64), default="")
    stage = Column(String(32), default="new")
    intent_level = Column(String(32), default="")
    sales_status = Column(String(32), default="new_lead", index=True)
    intent_score = Column(Integer, default=0)
    notes = Column(Text, default="")
    product = Column(String(32), default="", index=True)
    next_follow_up = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class StageLog(Base):
    __tablename__ = "stage_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    from_stage = Column(String(32), default="")
    to_stage = Column(String(32), nullable=False)
    trigger = Column(String(255), default="")
    created_at = Column(String(32), default=_now)


class CustomerChatLog(Base):
    __tablename__ = "customer_chat_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(String(32), default=_now)


class CustomerChatArchive(Base):
    __tablename__ = "customer_chat_archive"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(String(32), default="")
    archived_at = Column(String(32), default=_now)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    target = Column(String(128), default="")
    content = Column(Text, nullable=False)
    status = Column(String(32), default="pending")
    created_at = Column(String(32), default=_now)


class Lead(Base):
    """销售线索：公域/广告/表单/导入/微信入口统一沉淀，支持公海与自动分配"""
    __tablename__ = "leads"
    tenant_id = Column(Integer, default=0, index=True)
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), default="", index=True)
    display_id = Column(String(128), default="", index=True)
    customer_id = Column(Integer, default=None, index=True)
    name = Column(String(64), default="")
    phone = Column(String(32), default="", index=True)
    wechat_id = Column(String(128), default="", index=True)
    unionid = Column(String(128), default="", index=True)
    nickname = Column(String(128), default="")
    source = Column(String(32), default="import", index=True)
    channel_id = Column(String(64), default="", index=True)
    identity = Column(String(32), default="")
    level = Column(String(32), default="")
    goal = Column(String(64), default="")
    budget = Column(String(64), default="")
    interest = Column(String(64), default="")
    stage = Column(String(32), default="new")
    intent_level = Column(String(32), default="")
    intent_score = Column(Integer, default=0)
    status = Column(String(32), default="assigned", index=True)
    owner = Column(String(64), default="", index=True)
    sales_status = Column(String(32), default="new_lead", index=True)
    notes = Column(Text, default="")
    product = Column(String(32), default="", index=True)
    next_follow_up = Column(String(32), default="")
    assigned_at = Column(String(32), default="")
    last_follow_at = Column(String(32), default="")
    last_message_at = Column(String(32), default="")
    sla_due_at = Column(String(32), default="")
    recycled_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class MessageDedup(Base):
    __tablename__ = "message_dedup"
    id = Column(Integer, primary_key=True, autoincrement=True)
    msg_id = Column(String(128), unique=True, nullable=False, index=True)
    source = Column(String(32), default="")
    created_at = Column(String(32), default=_now)


class BehaviorEvent(Base):
    __tablename__ = "behavior_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), default="", index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    event_type = Column(String(32), default="", index=True)
    event_value = Column(String(128), default="")
    score = Column(Integer, default=0)
    created_at = Column(String(32), default=_now)


class FollowupTask(Base):
    __tablename__ = "followup_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), default="", index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    node = Column(Integer, default=1)
    node_label = Column(String(32), default="1h")
    due_at = Column(String(32), default="", index=True)
    status = Column(String(32), default="pending", index=True)
    result = Column(String(32), default="")
    source_script_id = Column(Integer, nullable=True)
    channel = Column(String(32), default="official")
    content = Column(Text, default="")
    sent_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Order(Base):
    __tablename__ = "orders"
    tenant_id = Column(Integer, default=0, index=True)
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(64), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    customer_name = Column(String(64), default="")
    phone = Column(String(32), default="", index=True)
    product_name = Column(String(128), default="")
    amount = Column(Float, default=0)
    status = Column(String(32), default="draft", index=True)
    pay_method = Column(String(32), default="")
    paid_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    amount = Column(Float, default=0)
    method = Column(String(32), default="")
    transaction_id = Column(String(128), default="")
    status = Column(String(32), default="pending")
    paid_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)


class AfterSale(Base):
    __tablename__ = "after_sales"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    reason = Column(Text, default="")
    status = Column(String(32), default="open", index=True)
    handler = Column(String(64), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class QualityReport(Base):
    __tablename__ = "quality_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    score = Column(Integer, default=0)
    sop_score = Column(Integer, default=0)
    tone_score = Column(Integer, default=0)
    issues = Column(Text, default="")
    samples = Column(Text, default="")
    created_at = Column(String(32), default=_now)


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    tenant_id = Column(Integer, default=0, index=True)
    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), default="", index=True)
    version = Column(Integer, default=1)
    file_hash = Column(String(64), default="")
    size = Column(Integer, default=0)
    active = Column(Boolean, default=False)
    status = Column(String(16), default="pending")
    document_id = Column(Integer, default=None, index=True)
    index_version_id = Column(Integer, default=None, index=True)
    reviewed_by = Column(String(64), default="")
    reviewed_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)


class KnowledgeDocument(Base):
    """租户知识文档主记录。"""
    __tablename__ = "knowledge_documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, nullable=False, index=True)
    filename = Column(String(255), default="", index=True)
    source_path = Column(Text, default="")
    file_hash = Column(String(64), default="", index=True)
    size = Column(Integer, default=0)
    status = Column(String(16), default="pending", index=True)
    active = Column(Boolean, default=False, index=True)
    version = Column(Integer, default=1)
    metadata_json = Column(Text, default="{}")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class KnowledgeIndexVersion(Base):
    """租户知识索引版本，用于原子发布和回滚。"""
    __tablename__ = "knowledge_index_versions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, nullable=False, index=True)
    version_name = Column(String(64), default="", index=True)
    status = Column(String(16), default="building", index=True)
    chunk_count = Column(Integer, default=0)
    error = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    activated_at = Column(String(32), default="")
    retired_at = Column(String(32), default="")


class KnowledgeChunk(Base):
    """租户知识切片；embedding_json 供 SQLite 回退，PG 使用额外的向量列。"""
    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, nullable=False, index=True)
    document_id = Column(Integer, default=None, index=True)
    index_version_id = Column(Integer, default=None, index=True)
    chunk_index = Column(Integer, default=0)
    content = Column(Text, default="")
    metadata_json = Column(Text, default="{}")
    embedding_json = Column(Text, default="[]")
    created_at = Column(String(32), default=_now)


class ApiKeyAccount(Base):
    """可吊销、可轮换、带租户和权限范围的服务账号 Key。"""
    __tablename__ = "api_key_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, nullable=False, index=True)
    name = Column(String(128), default="")
    key_hash = Column(String(128), unique=True, nullable=False, index=True)
    role = Column(String(32), default="service", index=True)
    scopes_json = Column(Text, default="[]")
    status = Column(String(16), default="active", index=True)
    expires_at = Column(String(32), default="")
    last_used_at = Column(String(32), default="")
    created_by = Column(String(64), default="")
    created_at = Column(String(32), default=_now)


class ConsentLog(Base):
    __tablename__ = "consent_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, nullable=False, index=True)
    session_id = Column(String(128), default="", index=True)
    source = Column(String(32), default="")
    content = Column(Text, default="")
    status = Column(String(16), default="granted")
    created_at = Column(String(32), default=_now)


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, nullable=False, index=True)
    session_id = Column(String(128), default="", index=True)
    applicant = Column(String(128), default="")
    reason = Column(Text, default="")
    status = Column(String(16), default="pending", index=True)
    error = Column(Text, default="")
    result_json = Column(Text, default="{}")
    attempts = Column(Integer, default=0)
    next_retry_at = Column(String(32), default="", index=True)
    created_at = Column(String(32), default=_now)
    handled_at = Column(String(32), default="")
    handler = Column(String(64), default="")


class HandoverRequest(Base):
    __tablename__ = "handover_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), default="", index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    source = Column(String(32), default="wechat")
    reason = Column(Text, default="")
    status = Column(String(32), default="requested", index=True)
    owner = Column(String(64), default="")
    created_at = Column(String(32), default=_now)
    assigned_at = Column(String(32), default="")
    done_at = Column(String(32), default="")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String(128), default="")
    action = Column(String(64), default="")
    resource = Column(String(255), default="")
    detail = Column(Text, default="")
    ip = Column(String(64), default="")
    level = Column(String(16), default="info")
    category = Column(String(32), default="system")
    created_at = Column(String(32), default=_now)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), default="")
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    product_name = Column(String(128), default="")
    amount = Column(Float, default=0)
    stage = Column(String(32), default="qualifying", index=True)
    win_rate = Column(Integer, default=0)
    owner = Column(String(64), default="", index=True)
    source = Column(String(32), default="")
    expected_close_at = Column(String(32), default="")
    last_activity_at = Column(String(32), default="")
    risk_level = Column(String(16), default="low")
    risk_reason = Column(String(255), default="")
    loss_reason = Column(String(255), default="")
    notes = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class PriceItem(Base):
    __tablename__ = "price_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(128), default="", index=True)
    sku = Column(String(64), default="", index=True)
    price = Column(Float, default=0)
    currency = Column(String(16), default="CNY")
    active = Column(Boolean, default=True)
    description = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Quote(Base):
    __tablename__ = "quotes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_no = Column(String(64), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    customer_name = Column(String(64), default="")
    product_name = Column(String(128), default="")
    base_amount = Column(Float, default=0)
    discount_rate = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    total_amount = Column(Float, default=0)
    status = Column(String(32), default="draft", index=True)
    version = Column(Integer, default=1)
    valid_until = Column(String(32), default="")
    notes = Column(Text, default="")
    created_by = Column(String(64), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class QuoteLine(Base):
    __tablename__ = "quote_lines"
    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_id = Column(Integer, nullable=False, index=True)
    product_name = Column(String(128), default="")
    price = Column(Float, default=0)
    quantity = Column(Integer, default=1)
    amount = Column(Float, default=0)


class Contract(Base):
    __tablename__ = "contracts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_no = Column(String(64), unique=True, nullable=False, index=True)
    quote_id = Column(Integer, nullable=True, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    customer_name = Column(String(64), default="")
    product_name = Column(String(128), default="")
    amount = Column(Float, default=0)
    status = Column(String(32), default="draft", index=True)
    terms = Column(Text, default="")
    risk_level = Column(String(16), default="low")
    risk_reason = Column(String(255), default="")
    signed_at = Column(String(32), default="")
    expires_at = Column(String(32), default="")
    created_by = Column(String(64), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class ApprovalFlow(Base):
    __tablename__ = "approval_flows"
    id = Column(Integer, primary_key=True, autoincrement=True)
    biz_type = Column(String(32), default="quote", index=True)
    biz_id = Column(Integer, nullable=False, index=True)
    requester = Column(String(64), default="")
    approver = Column(String(64), default="")
    status = Column(String(32), default="pending", index=True)
    comment = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    tracking_no = Column(String(128), default="")
    carrier = Column(String(64), default="")
    status = Column(String(32), default="pending", index=True)
    address = Column(String(255), default="")
    ship_at = Column(String(32), default="")
    delivered_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_no = Column(String(64), unique=True, nullable=False, index=True)
    order_id = Column(Integer, nullable=False, index=True)
    amount = Column(Float, default=0)
    title = Column(String(128), default="")
    tax_no = Column(String(64), default="")
    status = Column(String(32), default="unpaid", index=True)
    issued_at = Column(String(32), default="")
    paid_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class PaymentPlan(Base):
    __tablename__ = "payment_plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    plan_no = Column(String(64), default="")
    seq = Column(Integer, default=1)
    amount = Column(Float, default=0)
    due_at = Column(String(32), default="", index=True)
    status = Column(String(32), default="pending", index=True)
    paid_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Receivable(Base):
    __tablename__ = "receivables"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    plan_id = Column(Integer, nullable=True, index=True)
    amount = Column(Float, default=0)
    received_amount = Column(Float, default=0)
    status = Column(String(32), default="unpaid", index=True)
    due_at = Column(String(32), default="", index=True)
    last_received_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class BusinessProfile(Base):
    __tablename__ = "business_profiles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    company_name = Column(String(128), default="")
    unified_code = Column(String(64), default="")
    legal_person = Column(String(64), default="")
    registered_capital = Column(String(64), default="")
    industry = Column(String(64), default="")
    address = Column(String(255), default="")
    risk_summary = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Stakeholder(Base):
    __tablename__ = "stakeholders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    name = Column(String(64), default="")
    role = Column(String(64), default="")
    relation = Column(String(64), default="")
    company = Column(String(128), default="")
    phone = Column(String(32), default="")
    wechat_id = Column(String(128), default="")
    influence = Column(String(16), default="medium")
    notes = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class CustomerTag(Base):
    __tablename__ = "customer_tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    tag = Column(String(64), default="", index=True)
    source = Column(String(32), default="manual")
    created_at = Column(String(32), default=_now)


class RiskEvent(Base):
    __tablename__ = "risk_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    risk_type = Column(String(64), default="", index=True)
    level = Column(String(16), default="medium")
    content = Column(Text, default="")
    source = Column(String(32), default="manual")
    status = Column(String(32), default="open", index=True)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class ChannelJourney(Base):
    __tablename__ = "channel_journey"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    channel = Column(String(32), default="", index=True)
    action = Column(String(64), default="")
    detail = Column(Text, default="")
    created_at = Column(String(32), default=_now)


class SopTemplate(Base):
    __tablename__ = "sop_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), default="", index=True)
    stage = Column(String(32), default="", index=True)
    steps_json = Column(Text, default="[]")
    active = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class SopExecution(Base):
    __tablename__ = "sop_executions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    stage = Column(String(32), default="", index=True)
    step_index = Column(Integer, default=1)
    step_name = Column(String(128), default="")
    due_hours = Column(Integer, default=24)
    due_at = Column(String(32), default="", index=True)
    status = Column(String(32), default="pending", index=True)
    done_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class NurtureCampaign(Base):
    __tablename__ = "nurture_campaigns"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), default="", index=True)
    status = Column(String(32), default="draft", index=True)
    trigger_type = Column(String(32), default="stage")
    trigger_value = Column(String(64), default="")
    description = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class NurtureRule(Base):
    __tablename__ = "nurture_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    sequence = Column(Integer, default=1)
    condition_type = Column(String(32), default="always")
    condition_value = Column(String(64), default="")
    content = Column(Text, default="")
    delay_hours = Column(Integer, default=0)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class NurtureEvent(Base):
    __tablename__ = "nurture_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    rule_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    personalized_content = Column(Text, default="")
    status = Column(String(32), default="pending", index=True)
    sent_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_no = Column(String(64), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    title = Column(String(255), default="")
    description = Column(Text, default="")
    priority = Column(String(16), default="medium", index=True)
    category = Column(String(64), default="")
    status = Column(String(32), default="open", index=True)
    owner = Column(String(64), default="", index=True)
    sla_due_at = Column(String(32), default="", index=True)
    resolved_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class TicketEvent(Base):
    __tablename__ = "ticket_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, nullable=False, index=True)
    action = Column(String(64), default="")
    content = Column(Text, default="")
    actor = Column(String(64), default="")
    created_at = Column(String(32), default=_now)


class Visit(Base):
    __tablename__ = "visits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    order_id = Column(Integer, nullable=True, index=True)
    visit_type = Column(String(32), default="followup")
    content = Column(Text, default="")
    next_visit_at = Column(String(32), default="")
    owner = Column(String(64), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), default="", index=True)
    channel = Column(String(32), default="official", index=True)
    status = Column(String(32), default="draft", index=True)
    budget = Column(Float, default=0)
    cost = Column(Float, default=0)
    start_at = Column(String(32), default="")
    end_at = Column(String(32), default="")
    target = Column(String(64), default="")
    description = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class AdMetric(Base):
    __tablename__ = "ad_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    metric_date = Column(String(16), default="", index=True)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    cost = Column(Float, default=0)
    revenue = Column(Float, default=0)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class RepurchasePlan(Base):
    __tablename__ = "repurchase_plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=True, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    session_id = Column(String(128), default="", index=True)
    product_name = Column(String(128), default="")
    plan_date = Column(String(32), default="", index=True)
    status = Column(String(32), default="pending", index=True)
    note = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class CustomField(Base):
    __tablename__ = "custom_fields"
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity = Column(String(32), default="customer", index=True)
    field_name = Column(String(64), default="")
    field_key = Column(String(64), default="")
    field_type = Column(String(32), default="text")
    options = Column(Text, default="")
    required = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    sort = Column(Integer, default=0)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"
    id = Column(Integer, primary_key=True, autoincrement=True)
    entity = Column(String(32), default="customer", index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    field_key = Column(String(64), default="", index=True)
    value = Column(Text, default="")
    updated_at = Column(String(32), default=_now)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), default="", unique=True, index=True)
    permissions = Column(Text, default="[]")
    description = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class TeamMember(Base):
    __tablename__ = "team_members"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), default="default", index=True)
    name = Column(String(64), default="")
    nickname = Column(String(128), default="", index=True)
    role = Column(String(64), default="sales")
    phone = Column(String(32), default="")
    email = Column(String(128), default="")
    status = Column(String(32), default="active", index=True)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class AiReport(Base):
    __tablename__ = "ai_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    report_type = Column(String(32), default="daily_briefing", index=True)
    scope = Column(String(255), default="")
    content = Column(Text, default="")
    meta = Column(Text, default="{}")
    created_at = Column(String(32), default=_now)


class SalesCase(Base):
    __tablename__ = "sales_cases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), default="")
    case_type = Column(String(32), default="general", index=True)
    source = Column(String(32), default="manual")
    channel = Column(String(32), default="")
    content = Column(Text, default="")
    key_turns = Column(Text, default="")
    objections = Column(Text, default="")
    winning_points = Column(Text, default="")
    mistakes = Column(Text, default="")
    result = Column(String(32), default="")
    tags = Column(String(255), default="")
    active = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class ProductKnowledge(Base):
    __tablename__ = "product_knowledge"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(128), default="", index=True)
    target_customer = Column(String(255), default="")
    solves = Column(Text, default="")
    selling_points = Column(Text, default="")
    price = Column(String(64), default="")
    after_sales = Column(Text, default="")
    risk_limits = Column(Text, default="")
    proof = Column(Text, default="")
    active = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class ObjectionResponse(Base):
    __tablename__ = "objection_responses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger_scene = Column(String(255), default="", index=True)
    standard_reply = Column(Text, default="")
    evidence = Column(Text, default="")
    next_step = Column(Text, default="")
    active = Column(Boolean, default=True)
    sort = Column(Integer, default=0)
    created_at = Column(String(32), default=_now)


class CompetitorResponse(Base):
    __tablename__ = "competitor_responses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    competitor = Column(String(128), default="", index=True)
    customer_saying = Column(String(255), default="")
    differentiator_1 = Column(String(255), default="")
    differentiator_2 = Column(String(255), default="")
    differentiator_3 = Column(String(255), default="")
    standard_reply = Column(Text, default="")
    active = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)


class FollowupScript(Base):
    __tablename__ = "followup_scripts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    followup_scene = Column(String(128), default="", index=True)
    trigger_condition = Column(String(255), default="")
    value_point = Column(Text, default="")
    script_example = Column(Text, default="")
    next_goal = Column(Text, default="")
    delay_hours = Column(Integer, default=24)
    active = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)


class ConversationSummary(Base):
    __tablename__ = "conversation_summary"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), default="", index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    source = Column(String(32), default="")
    sales_status = Column(String(32), default="new_lead", index=True)
    core_concern = Column(String(255), default="")
    selection_criteria = Column(String(255), default="")
    evidence_given = Column(String(255), default="")
    next_follow_time = Column(String(32), default="")
    next_follow_reason = Column(String(255), default="")
    next_goal = Column(String(255), default="")
    raw_json = Column(Text, default="")
    created_at = Column(String(32), default=_now)


class Differentiator(Base):
    __tablename__ = "differentiators"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product = Column(String(128), default="")
    differentiator = Column(String(255), default="")
    evidence = Column(Text, default="")
    customer_concern = Column(String(128), default="")
    active = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)


class EvidenceLibrary(Base):
    __tablename__ = "evidence_library"
    id = Column(Integer, primary_key=True, autoincrement=True)
    evidence_type = Column(String(32), default="case", index=True)
    title = Column(String(255), default="")
    content = Column(Text, default="")
    link = Column(String(255), default="")
    scenario = Column(String(255), default="")
    active = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)


class KeyMomentTool(Base):
    __tablename__ = "key_moment_tools"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_type = Column(String(32), default="trial", index=True)
    name = Column(String(128), default="")
    description = Column(Text, default="")
    trigger_scene = Column(String(255), default="")
    active = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)


class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), default="", index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    order_id = Column(Integer, nullable=True, index=True)
    appointment_type = Column(String(32), default="trial")
    title = Column(String(255), default="")
    start_at = Column(String(32), default="", index=True)
    end_at = Column(String(32), default="")
    status = Column(String(32), default="pending", index=True)
    owner = Column(String(64), default="")
    note = Column(Text, default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), default="")
    coupon_type = Column(String(32), default="discount", index=True)
    value = Column(String(64), default="")
    min_amount = Column(Float, default=0)
    valid_days = Column(Integer, default=7)
    quota = Column(Integer, default=0)
    status = Column(String(32), default="active", index=True)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class UserCoupon(Base):
    __tablename__ = "user_coupons"
    id = Column(Integer, primary_key=True, autoincrement=True)
    coupon_id = Column(Integer, nullable=False, index=True)
    session_id = Column(String(128), default="", index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    status = Column(String(32), default="unused", index=True)
    expires_at = Column(String(32), default="")
    used_at = Column(String(32), default="")
    order_id = Column(Integer, nullable=True)
    created_at = Column(String(32), default=_now)


class PaymentLink(Base):
    __tablename__ = "payment_links"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    session_id = Column(String(128), default="", index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    title = Column(String(255), default="")
    amount = Column(Float, default=0)
    pay_method = Column(String(32), default="wechat")
    link = Column(String(255), default="")
    qr_text = Column(Text, default="")
    status = Column(String(32), default="pending", index=True)
    expires_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now)


class ConversationMetric(Base):
    __tablename__ = "conversation_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), default="", index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    source = Column(String(32), default="")
    stage = Column(String(32), default="")
    sales_status = Column(String(32), default="")
    core_concern = Column(String(255), default="")
    competitor_mentioned = Column(String(128), default="")
    emotion = Column(String(32), default="")
    has_next_step = Column(Boolean, default=False)
    gave_evidence = Column(Boolean, default=False)
    bound_differentiator = Column(Boolean, default=False)
    is_deal = Column(Boolean, default=False)
    followup_result = Column(String(32), default="")
    lost_reason = Column(String(255), default="")
    created_at = Column(String(32), default=_now)


class AbExperiment(Base):
    __tablename__ = "ab_experiments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), default="", index=True)
    kind = Column(String(32), default="script", index=True)
    control = Column(Text, default="")
    variant = Column(Text, default="")
    status = Column(String(32), default="draft", index=True)
    start_at = Column(String(32), default="")
    end_at = Column(String(32), default="")
    note = Column(Text, default="")
    created_at = Column(String(32), default=_now)


class AbRun(Base):
    __tablename__ = "ab_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(Integer, nullable=False, index=True)
    session_id = Column(String(128), default="", index=True)
    variant = Column(String(32), default="control")
    result = Column(String(32), default="")
    created_at = Column(String(32), default=_now)


class WeeklyReview(Base):
    __tablename__ = "weekly_reviews"
    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(String(16), default="", index=True)
    content = Column(Text, default="")
    metrics_json = Column(Text, default="{}")
    created_at = Column(String(32), default=_now)


class ComplianceRule(Base):
    __tablename__ = "compliance_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_type = Column(String(32), default="handover", index=True)
    trigger_words = Column(Text, default="")
    action = Column(String(32), default="handover")
    priority = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)
    description = Column(Text, default="")
    created_at = Column(String(32), default=_now)


class ConversationScore(Base):
    """每轮对话自动评分记录"""
    __tablename__ = "conversation_scores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), default="", index=True)
    customer_id = Column(Integer, default=None, index=True)
    product = Column(String(32), default="", index=True)
    # 四维评分
    conversion_score = Column(Integer, default=0)  # 转化推进 0-25
    compliance_score = Column(Integer, default=0)   # 合规性 0-25
    satisfaction_score = Column(Integer, default=0)  # 客户满意度 0-25
    response_score = Column(Integer, default=0)      # 响应质量 0-25
    total_score = Column(Integer, default=0)         # 总分 0-100
    # 详情
    score_details = Column(Text, default="")  # JSON: 各维度扣分原因
    prompt_version_id = Column(Integer, default=None, index=True)  # 关联的提示词版本
    experiment_id = Column(Integer, default=None, index=True)  # 关联的A/B实验
    experiment_variant = Column(String(32), default="")  # 实验组别
    created_at = Column(String(32), default=_now)


class PromptVersion(Base):
    """提示词版本管理"""
    __tablename__ = "prompt_versions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(Integer, default=1, index=True)
    content = Column(Text, default="")
    description = Column(String(255), default="")
    is_active = Column(Boolean, default=False, index=True)
    # 效果指标
    total_conversations = Column(Integer, default=0)
    avg_score = Column(Float, default=0.0)
    conversion_rate = Column(Float, default=0.0)  # 成交率
    avg_turns = Column(Float, default=0.0)  # 平均对话轮次
    compliance_violations = Column(Integer, default=0)
    created_at = Column(String(32), default=_now)
    activated_at = Column(String(32), default="")
    deactivated_at = Column(String(32), default="")


class OptimizationSuggestion(Base):
    """自动优化建议"""
    __tablename__ = "optimization_suggestions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    suggestion_type = Column(String(32), default="prompt", index=True)  # prompt/script/flow
    category = Column(String(64), default="")  # 转化/合规/满意度/效率
    title = Column(String(255), default="")
    description = Column(Text, default="")
    current_value = Column(Text, default="")  # 当前话术/配置
    suggested_value = Column(Text, default="")  # 建议的改进
    impact_score = Column(Float, default=0.0)  # 预估影响分
    data_basis = Column(Text, default="")  # 数据依据 JSON
    status = Column(String(32), default="pending", index=True)  # pending/approved/applied/rejected
    applied_at = Column(String(32), default="")


class BIReport(Base):
    """数据智能自定义报表配置"""
    __tablename__ = "bi_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, index=True)
    name = Column(String(128), default="", index=True)
    metric = Column(String(32), default="customers")
    dimension = Column(String(32), default="date")
    days = Column(Integer, default=30)
    filters_json = Column(Text, default="{}")
    created_by = Column(String(64), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class SalesWorkflow(Base):
    """销售流程：可配置工作流模板"""
    __tablename__ = "sales_workflows"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, index=True)
    name = Column(String(128), default="", index=True)
    trigger = Column(String(32), default="manual", index=True)
    enabled = Column(Boolean, default=True, index=True)
    nodes_json = Column(Text, default="[]")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class SalesWorkflowExecution(Base):
    """销售流程：工作流执行记录"""
    __tablename__ = "sales_workflow_executions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, nullable=False, index=True)
    tenant_id = Column(Integer, default=0, index=True)
    context_json = Column(Text, default="{}")
    status = Column(String(32), default="running", index=True)
    result_json = Column(Text, default="{}")
    started_at = Column(String(32), default="")
    finished_at = Column(String(32), default="")


class DispatchRule(Base):
    """销售流程：智能派单规则"""
    __tablename__ = "dispatch_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, index=True)
    name = Column(String(128), default="", index=True)
    strategy = Column(String(32), default="round_robin")
    enabled = Column(Boolean, default=True, index=True)
    params_json = Column(Text, default="{}")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class ChannelSession(Base):
    """商用中心：统一多渠道会话"""
    __tablename__ = "channel_sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, index=True)
    channel = Column(String(32), default="webchat", index=True)
    external_id = Column(String(128), default="", index=True)
    session_key = Column(String(128), default="", index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    nickname = Column(String(128), default="")
    status = Column(String(32), default="waiting", index=True)
    priority = Column(Integer, default=0, index=True)
    route_target = Column(String(32), default="robot")
    assigned_agent = Column(String(64), default="")
    source_page = Column(String(255), default="")
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)
    closed_at = Column(String(32), default="")


class ChannelMessage(Base):
    """商用中心：统一消息记录"""
    __tablename__ = "channel_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, index=True)
    session_id = Column(Integer, nullable=False, index=True)
    channel = Column(String(32), default="webchat")
    direction = Column(String(8), default="in")
    content = Column(Text, default="")
    msg_type = Column(String(16), default="text")
    created_at = Column(String(32), default=_now)


class RouteRule(Base):
    """商用中心：智能路由规则"""
    __tablename__ = "route_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, index=True)
    name = Column(String(128), default="", index=True)
    priority = Column(Integer, default=0)
    condition_json = Column(Text, default="{}")
    target = Column(String(32), default="robot")
    enabled = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class MarketingJourney(Base):
    """商用中心：营销自动化旅程"""
    __tablename__ = "marketing_journeys"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, index=True)
    name = Column(String(128), default="", index=True)
    trigger = Column(String(32), default="manual")
    nodes_json = Column(Text, default="[]")
    enabled = Column(Boolean, default=True)
    daily_limit = Column(Integer, default=100)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class ModerationRule(Base):
    """商用中心：内容安全规则"""
    __tablename__ = "moderation_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, default=0, index=True)
    name = Column(String(128), default="", index=True)
    keywords = Column(Text, default="")
    action = Column(String(16), default="block")
    enabled = Column(Boolean, default=True)
    created_at = Column(String(32), default=_now)
    updated_at = Column(String(32), default=_now)


class PersonalWechatReplyTask(Base):
    """个人微信本地桥接：回复任务与发送回执"""
    __tablename__ = "personal_wechat_reply_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, default=0, index=True)
    source_message_id = Column(String(160), default="", index=True)
    account_id = Column(String(128), default="", index=True)
    session_id = Column(Integer, nullable=True, index=True)
    target_type = Column(String(16), default="contact")
    target_name = Column(String(128), default="")
    target_username = Column(String(128), default="", index=True)
    content = Column(Text, default="")
    mode = Column(String(16), default="draft", index=True)
    status = Column(String(24), default="generating", index=True)
    error = Column(Text, default="")
    claimed_by = Column(String(128), default="")
    claimed_at = Column(String(32), default="")
    lease_expires_at = Column(String(32), default="", index=True)
    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    next_retry_at = Column(String(32), default="", index=True)
    failure_code = Column(String(64), default="", index=True)
    failure_stage = Column(String(32), default="")
    send_token = Column(String(64), default="", index=True)
    send_started_at = Column(String(32), default="")
    send_confirmed_at = Column(String(32), default="")
    manual_review_at = Column(String(32), default="")
    diagnostic_path = Column(Text, default="")
    expires_at = Column(String(32), default="", index=True)
    ack_at = Column(String(32), default="")
    created_at = Column(String(32), default=_now, index=True)
    updated_at = Column(String(32), default=_now)


class PersonalWechatBridgeInstance(Base):
    """个人微信本地桥接实例：前端实时状态"""
    __tablename__ = "personal_wechat_bridge_instances"
    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(String(128), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, default=0, index=True)
    account_id = Column(String(128), default="", index=True)
    status = Column(String(24), default="online", index=True)
    mode = Column(String(16), default="draft")
    auto_discover_contacts = Column(Boolean, default=False)
    notify_on_message = Column(Boolean, default=True)
    recognition_enabled = Column(Boolean, default=False)
    detect_wechat_login = Column(Boolean, default=True)
    wechat_login_detected = Column(Boolean, default=False)
    poll_interval_seconds = Column(Integer, default=10)
    last_message_at = Column(String(32), default="")
    last_reply_at = Column(String(32), default="")
    last_error = Column(Text, default="")
    detail_json = Column(Text, default="{}")
    last_seen = Column(String(32), default=_now, index=True)
    updated_at = Column(String(32), default=_now)


TENANT_SCOPED_TABLES = {
    "customers",
    "stage_log",
    "customer_chat_log",
    "customer_chat_archive",
    "notifications",
    "message_dedup",
    "audit_logs",
    "behavior_events",
    "followup_tasks",
    "payments",
    "after_sales",
    "quality_reports",
    "handover_requests",
    "opportunities",
    "price_items",
    "quotes",
    "quote_lines",
    "contracts",
    "approval_flows",
    "shipments",
    "invoices",
    "payment_plans",
    "receivables",
    "business_profiles",
    "stakeholders",
    "customer_tags",
    "risk_events",
    "channel_journey",
    "sop_templates",
    "sop_executions",
    "nurture_campaigns",
    "nurture_rules",
    "nurture_events",
    "tickets",
    "ticket_events",
    "visits",
    "campaigns",
    "ad_metrics",
    "repurchase_plans",
    "custom_fields",
    "custom_field_values",
    "roles",
    "ai_reports",
    "sales_cases",
    "product_knowledge",
    "objection_responses",
    "competitor_responses",
    "followup_scripts",
    "conversation_summary",
    "differentiators",
    "evidence_library",
    "key_moment_tools",
    "appointments",
    "coupons",
    "user_coupons",
    "payment_links",
    "conversation_metrics",
    "ab_experiments",
    "ab_runs",
    "weekly_reviews",
    "compliance_rules",
    "conversation_scores",
    "prompt_versions",
    "optimization_suggestions",
}


def _install_tenant_columns() -> None:
    """为历史模型补齐 tenant_id，保持旧调用兼容并统一 ORM 元数据。"""
    for model in Base.__subclasses__():
        table = getattr(model, "__table__", None)
        if table is None or table.name not in TENANT_SCOPED_TABLES:
            continue
        if "tenant_id" in table.c:
            continue
        column = Column(
            "tenant_id",
            Integer,
            default=0,
            nullable=False,
            server_default="0",
        )
        table.append_column(column)
        setattr(model, "tenant_id", column)


_install_tenant_columns()
