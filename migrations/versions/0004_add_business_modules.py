"""add business modules: opportunity, cpq, finance, portrait, sop, nurture, ticket, marketing, platform

Revision ID: 0004_add_business_modules
Revises: 0003_add_business_tables
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_add_business_modules"
down_revision = "0003_add_business_tables"
branch_labels = None
depends_on = None


def _string(name, length=32, default="", index=False):
    col = sa.Column(name, sa.String(length), server_default=default)
    if index:
        return col
    return col


def upgrade():
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), server_default=""),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("product_name", sa.String(128), server_default=""),
        sa.Column("amount", sa.Float(), server_default="0"),
        sa.Column("stage", sa.String(32), server_default="qualifying"),
        sa.Column("win_rate", sa.Integer(), server_default="0"),
        sa.Column("owner", sa.String(64), server_default=""),
        sa.Column("source", sa.String(32), server_default=""),
        sa.Column("expected_close_at", sa.String(32), server_default=""),
        sa.Column("last_activity_at", sa.String(32), server_default=""),
        sa.Column("risk_level", sa.String(16), server_default="low"),
        sa.Column("risk_reason", sa.String(255), server_default=""),
        sa.Column("loss_reason", sa.String(255), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("customer_id", "lead_id", "session_id", "stage", "owner"):
        op.create_index(f"ix_opportunities_{col}", "opportunities", [col])

    op.create_table(
        "price_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_name", sa.String(128), server_default=""),
        sa.Column("sku", sa.String(64), server_default=""),
        sa.Column("price", sa.Float(), server_default="0"),
        sa.Column("currency", sa.String(16), server_default="CNY"),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_price_items_product_name", "price_items", ["product_name"])
    op.create_index("ix_price_items_sku", "price_items", ["sku"])

    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quote_no", sa.String(64), nullable=False, unique=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("customer_name", sa.String(64), server_default=""),
        sa.Column("product_name", sa.String(128), server_default=""),
        sa.Column("base_amount", sa.Float(), server_default="0"),
        sa.Column("discount_rate", sa.Float(), server_default="0"),
        sa.Column("discount_amount", sa.Float(), server_default="0"),
        sa.Column("total_amount", sa.Float(), server_default="0"),
        sa.Column("status", sa.String(32), server_default="draft"),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("valid_until", sa.String(32), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_by", sa.String(64), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_quotes_quote_no", "quotes", ["quote_no"])
    op.create_index("ix_quotes_customer_id", "quotes", ["customer_id"])
    op.create_index("ix_quotes_lead_id", "quotes", ["lead_id"])
    op.create_index("ix_quotes_session_id", "quotes", ["session_id"])
    op.create_index("ix_quotes_status", "quotes", ["status"])

    op.create_table(
        "quote_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quote_id", sa.Integer(), nullable=False),
        sa.Column("product_name", sa.String(128), server_default=""),
        sa.Column("price", sa.Float(), server_default="0"),
        sa.Column("quantity", sa.Integer(), server_default="1"),
        sa.Column("amount", sa.Float(), server_default="0"),
    )
    op.create_index("ix_quote_lines_quote_id", "quote_lines", ["quote_id"])

    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_no", sa.String(64), nullable=False, unique=True),
        sa.Column("quote_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("customer_name", sa.String(64), server_default=""),
        sa.Column("product_name", sa.String(128), server_default=""),
        sa.Column("amount", sa.Float(), server_default="0"),
        sa.Column("status", sa.String(32), server_default="draft"),
        sa.Column("terms", sa.Text(), server_default=""),
        sa.Column("risk_level", sa.String(16), server_default="low"),
        sa.Column("risk_reason", sa.String(255), server_default=""),
        sa.Column("signed_at", sa.String(32), server_default=""),
        sa.Column("expires_at", sa.String(32), server_default=""),
        sa.Column("created_by", sa.String(64), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_contracts_contract_no", "contracts", ["contract_no"])
    op.create_index("ix_contracts_quote_id", "contracts", ["quote_id"])
    op.create_index("ix_contracts_customer_id", "contracts", ["customer_id"])
    op.create_index("ix_contracts_lead_id", "contracts", ["lead_id"])
    op.create_index("ix_contracts_session_id", "contracts", ["session_id"])
    op.create_index("ix_contracts_status", "contracts", ["status"])

    op.create_table(
        "approval_flows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("biz_type", sa.String(32), server_default="quote"),
        sa.Column("biz_id", sa.Integer(), nullable=False),
        sa.Column("requester", sa.String(64), server_default=""),
        sa.Column("approver", sa.String(64), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("comment", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_approval_flows_biz_type", "approval_flows", ["biz_type"])
    op.create_index("ix_approval_flows_biz_id", "approval_flows", ["biz_id"])
    op.create_index("ix_approval_flows_status", "approval_flows", ["status"])

    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("tracking_no", sa.String(128), server_default=""),
        sa.Column("carrier", sa.String(64), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("address", sa.String(255), server_default=""),
        sa.Column("ship_at", sa.String(32), server_default=""),
        sa.Column("delivered_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_shipments_order_id", "shipments", ["order_id"])
    op.create_index("ix_shipments_status", "shipments", ["status"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("invoice_no", sa.String(64), nullable=False, unique=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), server_default="0"),
        sa.Column("title", sa.String(128), server_default=""),
        sa.Column("tax_no", sa.String(64), server_default=""),
        sa.Column("status", sa.String(32), server_default="unpaid"),
        sa.Column("issued_at", sa.String(32), server_default=""),
        sa.Column("paid_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_invoices_invoice_no", "invoices", ["invoice_no"])
    op.create_index("ix_invoices_order_id", "invoices", ["order_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])

    op.create_table(
        "payment_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("plan_no", sa.String(64), server_default=""),
        sa.Column("seq", sa.Integer(), server_default="1"),
        sa.Column("amount", sa.Float(), server_default="0"),
        sa.Column("due_at", sa.String(32), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("paid_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_payment_plans_order_id", "payment_plans", ["order_id"])
    op.create_index("ix_payment_plans_due_at", "payment_plans", ["due_at"])
    op.create_index("ix_payment_plans_status", "payment_plans", ["status"])

    op.create_table(
        "receivables",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), server_default="0"),
        sa.Column("received_amount", sa.Float(), server_default="0"),
        sa.Column("status", sa.String(32), server_default="unpaid"),
        sa.Column("due_at", sa.String(32), server_default=""),
        sa.Column("last_received_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_receivables_order_id", "receivables", ["order_id"])
    op.create_index("ix_receivables_plan_id", "receivables", ["plan_id"])
    op.create_index("ix_receivables_status", "receivables", ["status"])
    op.create_index("ix_receivables_due_at", "receivables", ["due_at"])

    op.create_table(
        "business_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("company_name", sa.String(128), server_default=""),
        sa.Column("unified_code", sa.String(64), server_default=""),
        sa.Column("legal_person", sa.String(64), server_default=""),
        sa.Column("registered_capital", sa.String(64), server_default=""),
        sa.Column("industry", sa.String(64), server_default=""),
        sa.Column("address", sa.String(255), server_default=""),
        sa.Column("risk_summary", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("customer_id", "lead_id", "session_id"):
        op.create_index(f"ix_business_profiles_{col}", "business_profiles", [col])

    op.create_table(
        "stakeholders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("name", sa.String(64), server_default=""),
        sa.Column("role", sa.String(64), server_default=""),
        sa.Column("relation", sa.String(64), server_default=""),
        sa.Column("company", sa.String(128), server_default=""),
        sa.Column("phone", sa.String(32), server_default=""),
        sa.Column("wechat_id", sa.String(128), server_default=""),
        sa.Column("influence", sa.String(16), server_default="medium"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("customer_id", "lead_id", "session_id"):
        op.create_index(f"ix_stakeholders_{col}", "stakeholders", [col])

    op.create_table(
        "customer_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("tag", sa.String(64), server_default=""),
        sa.Column("source", sa.String(32), server_default="manual"),
        sa.Column("created_at", sa.String(32)),
    )
    for col in ("customer_id", "lead_id", "session_id", "tag"):
        op.create_index(f"ix_customer_tags_{col}", "customer_tags", [col])

    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("risk_type", sa.String(64), server_default=""),
        sa.Column("level", sa.String(16), server_default="medium"),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("source", sa.String(32), server_default="manual"),
        sa.Column("status", sa.String(32), server_default="open"),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("customer_id", "lead_id", "session_id", "risk_type", "status"):
        op.create_index(f"ix_risk_events_{col}", "risk_events", [col])

    op.create_table(
        "channel_journey",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("channel", sa.String(32), server_default=""),
        sa.Column("action", sa.String(64), server_default=""),
        sa.Column("detail", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
    )
    for col in ("customer_id", "lead_id", "session_id", "channel"):
        op.create_index(f"ix_channel_journey_{col}", "channel_journey", [col])

    op.create_table(
        "sop_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), server_default=""),
        sa.Column("stage", sa.String(32), server_default=""),
        sa.Column("steps_json", sa.Text(), server_default="[]"),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_sop_templates_name", "sop_templates", ["name"])
    op.create_index("ix_sop_templates_stage", "sop_templates", ["stage"])

    op.create_table(
        "sop_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("stage", sa.String(32), server_default=""),
        sa.Column("step_index", sa.Integer(), server_default="1"),
        sa.Column("step_name", sa.String(128), server_default=""),
        sa.Column("due_hours", sa.Integer(), server_default="24"),
        sa.Column("due_at", sa.String(32), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("done_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("template_id", "customer_id", "lead_id", "session_id", "stage", "due_at", "status"):
        op.create_index(f"ix_sop_executions_{col}", "sop_executions", [col])

    op.create_table(
        "nurture_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), server_default=""),
        sa.Column("status", sa.String(32), server_default="draft"),
        sa.Column("trigger_type", sa.String(32), server_default="stage"),
        sa.Column("trigger_value", sa.String(64), server_default=""),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_nurture_campaigns_name", "nurture_campaigns", ["name"])
    op.create_index("ix_nurture_campaigns_status", "nurture_campaigns", ["status"])

    op.create_table(
        "nurture_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), server_default="1"),
        sa.Column("condition_type", sa.String(32), server_default="always"),
        sa.Column("condition_value", sa.String(64), server_default=""),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("delay_hours", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_nurture_rules_campaign_id", "nurture_rules", ["campaign_id"])

    op.create_table(
        "nurture_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("personalized_content", sa.Text(), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("sent_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("campaign_id", "rule_id", "customer_id", "lead_id", "session_id", "status"):
        op.create_index(f"ix_nurture_events_{col}", "nurture_events", [col])

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticket_no", sa.String(64), nullable=False, unique=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("title", sa.String(255), server_default=""),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("priority", sa.String(16), server_default="medium"),
        sa.Column("category", sa.String(64), server_default=""),
        sa.Column("status", sa.String(32), server_default="open"),
        sa.Column("owner", sa.String(64), server_default=""),
        sa.Column("sla_due_at", sa.String(32), server_default=""),
        sa.Column("resolved_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_tickets_ticket_no", "tickets", ["ticket_no"])
    for col in ("customer_id", "lead_id", "session_id", "priority", "status", "owner", "sla_due_at"):
        op.create_index(f"ix_tickets_{col}", "tickets", [col])

    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(64), server_default=""),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("actor", sa.String(64), server_default=""),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_ticket_events_ticket_id", "ticket_events", ["ticket_id"])

    op.create_table(
        "visits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("visit_type", sa.String(32), server_default="followup"),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("next_visit_at", sa.String(32), server_default=""),
        sa.Column("owner", sa.String(64), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("customer_id", "lead_id", "session_id", "order_id"):
        op.create_index(f"ix_visits_{col}", "visits", [col])

    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), server_default=""),
        sa.Column("channel", sa.String(32), server_default="official"),
        sa.Column("status", sa.String(32), server_default="draft"),
        sa.Column("budget", sa.Float(), server_default="0"),
        sa.Column("cost", sa.Float(), server_default="0"),
        sa.Column("start_at", sa.String(32), server_default=""),
        sa.Column("end_at", sa.String(32), server_default=""),
        sa.Column("target", sa.String(64), server_default=""),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("name", "channel", "status"):
        op.create_index(f"ix_campaigns_{col}", "campaigns", [col])

    op.create_table(
        "ad_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("metric_date", sa.String(16), server_default=""),
        sa.Column("impressions", sa.Integer(), server_default="0"),
        sa.Column("clicks", sa.Integer(), server_default="0"),
        sa.Column("conversions", sa.Integer(), server_default="0"),
        sa.Column("cost", sa.Float(), server_default="0"),
        sa.Column("revenue", sa.Float(), server_default="0"),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_ad_metrics_campaign_id", "ad_metrics", ["campaign_id"])
    op.create_index("ix_ad_metrics_metric_date", "ad_metrics", ["metric_date"])

    op.create_table(
        "repurchase_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("product_name", sa.String(128), server_default=""),
        sa.Column("plan_date", sa.String(32), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("note", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("order_id", "customer_id", "lead_id", "session_id", "plan_date", "status"):
        op.create_index(f"ix_repurchase_plans_{col}", "repurchase_plans", [col])

    op.create_table(
        "custom_fields",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity", sa.String(32), server_default="customer"),
        sa.Column("field_name", sa.String(64), server_default=""),
        sa.Column("field_key", sa.String(64), server_default=""),
        sa.Column("field_type", sa.String(32), server_default="text"),
        sa.Column("options", sa.Text(), server_default=""),
        sa.Column("required", sa.Boolean(), server_default="0"),
        sa.Column("enabled", sa.Boolean(), server_default="1"),
        sa.Column("sort", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_custom_fields_entity", "custom_fields", ["entity"])
    op.create_index("ix_custom_fields_field_key", "custom_fields", ["field_key"])

    op.create_table(
        "custom_field_values",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity", sa.String(32), server_default="customer"),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("field_key", sa.String(64), server_default=""),
        sa.Column("value", sa.Text(), server_default=""),
        sa.Column("updated_at", sa.String(32)),
    )
    for col in ("entity", "entity_id", "field_key"):
        op.create_index(f"ix_custom_field_values_{col}", "custom_field_values", [col])

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("permissions", sa.Text(), server_default="[]"),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_roles_name", "roles", ["name"])

    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), server_default="default"),
        sa.Column("name", sa.String(64), server_default=""),
        sa.Column("nickname", sa.String(128), server_default=""),
        sa.Column("role", sa.String(64), server_default="sales"),
        sa.Column("phone", sa.String(32), server_default=""),
        sa.Column("email", sa.String(128), server_default=""),
        sa.Column("status", sa.String(32), server_default="active"),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_team_members_tenant_id", "team_members", ["tenant_id"])
    op.create_index("ix_team_members_nickname", "team_members", ["nickname"])
    op.create_index("ix_team_members_status", "team_members", ["status"])

    op.create_table(
        "ai_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_type", sa.String(32), server_default="daily_briefing"),
        sa.Column("scope", sa.String(255), server_default=""),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("meta", sa.Text(), server_default="{}"),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_ai_reports_report_type", "ai_reports", ["report_type"])


def downgrade():
    tables = [
        "ai_reports",
        "team_members",
        "roles",
        "custom_field_values",
        "custom_fields",
        "repurchase_plans",
        "ad_metrics",
        "campaigns",
        "visits",
        "ticket_events",
        "tickets",
        "nurture_events",
        "nurture_rules",
        "nurture_campaigns",
        "sop_executions",
        "sop_templates",
        "channel_journey",
        "risk_events",
        "customer_tags",
        "stakeholders",
        "business_profiles",
        "receivables",
        "payment_plans",
        "invoices",
        "shipments",
        "approval_flows",
        "contracts",
        "quote_lines",
        "quotes",
        "price_items",
        "opportunities",
    ]
    for table in tables:
        op.drop_table(table)
