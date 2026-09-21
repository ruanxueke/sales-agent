"""add business tables

Revision ID: 0003_add_business_tables
Revises: 0002_add_leads
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_add_business_tables"
down_revision = "0002_add_leads"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "message_dedup",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("msg_id", sa.String(128), nullable=False, unique=True),
        sa.Column("source", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_message_dedup_msg_id", "message_dedup", ["msg_id"])

    op.create_table(
        "behavior_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(32), server_default=""),
        sa.Column("event_value", sa.String(128), server_default=""),
        sa.Column("score", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_behavior_events_session_id", "behavior_events", ["session_id"])
    op.create_index("ix_behavior_events_lead_id", "behavior_events", ["lead_id"])
    op.create_index("ix_behavior_events_event_type", "behavior_events", ["event_type"])

    op.create_table(
        "followup_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("node", sa.Integer(), server_default="1"),
        sa.Column("node_label", sa.String(32), server_default="1h"),
        sa.Column("due_at", sa.String(32), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("channel", sa.String(32), server_default="official"),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("sent_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_followup_tasks_session_id", "followup_tasks", ["session_id"])
    op.create_index("ix_followup_tasks_lead_id", "followup_tasks", ["lead_id"])
    op.create_index("ix_followup_tasks_customer_id", "followup_tasks", ["customer_id"])
    op.create_index("ix_followup_tasks_due_at", "followup_tasks", ["due_at"])
    op.create_index("ix_followup_tasks_status", "followup_tasks", ["status"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_no", sa.String(64), nullable=False, unique=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("customer_name", sa.String(64), server_default=""),
        sa.Column("phone", sa.String(32), server_default=""),
        sa.Column("product_name", sa.String(128), server_default=""),
        sa.Column("amount", sa.Float(), server_default="0"),
        sa.Column("status", sa.String(32), server_default="draft"),
        sa.Column("pay_method", sa.String(32), server_default=""),
        sa.Column("paid_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_orders_order_no", "orders", ["order_no"])
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_lead_id", "orders", ["lead_id"])
    op.create_index("ix_orders_session_id", "orders", ["session_id"])
    op.create_index("ix_orders_phone", "orders", ["phone"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), server_default="0"),
        sa.Column("method", sa.String(32), server_default=""),
        sa.Column("transaction_id", sa.String(128), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("paid_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])

    op.create_table(
        "after_sales",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("reason", sa.Text(), server_default=""),
        sa.Column("status", sa.String(32), server_default="open"),
        sa.Column("handler", sa.String(64), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_after_sales_order_id", "after_sales", ["order_id"])
    op.create_index("ix_after_sales_customer_id", "after_sales", ["customer_id"])
    op.create_index("ix_after_sales_session_id", "after_sales", ["session_id"])
    op.create_index("ix_after_sales_status", "after_sales", ["status"])

    op.create_table(
        "quality_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("score", sa.Integer(), server_default="0"),
        sa.Column("sop_score", sa.Integer(), server_default="0"),
        sa.Column("tone_score", sa.Integer(), server_default="0"),
        sa.Column("issues", sa.Text(), server_default=""),
        sa.Column("samples", sa.Text(), server_default=""),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_quality_reports_customer_id", "quality_reports", ["customer_id"])
    op.create_index("ix_quality_reports_session_id", "quality_reports", ["session_id"])

    op.create_table(
        "knowledge_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("filename", sa.String(255), server_default=""),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("file_hash", sa.String(64), server_default=""),
        sa.Column("size", sa.Integer(), server_default="0"),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_knowledge_versions_filename", "knowledge_versions", ["filename"])

    op.create_table(
        "handover_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(32), server_default="wechat"),
        sa.Column("reason", sa.Text(), server_default=""),
        sa.Column("status", sa.String(32), server_default="requested"),
        sa.Column("owner", sa.String(64), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("assigned_at", sa.String(32), server_default=""),
        sa.Column("done_at", sa.String(32), server_default=""),
    )
    op.create_index("ix_handover_requests_session_id", "handover_requests", ["session_id"])
    op.create_index("ix_handover_requests_customer_id", "handover_requests", ["customer_id"])
    op.create_index("ix_handover_requests_lead_id", "handover_requests", ["lead_id"])
    op.create_index("ix_handover_requests_status", "handover_requests", ["status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(128), server_default=""),
        sa.Column("action", sa.String(64), server_default=""),
        sa.Column("resource", sa.String(255), server_default=""),
        sa.Column("detail", sa.Text(), server_default=""),
        sa.Column("ip", sa.String(64), server_default=""),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade():
    for table in (
        "audit_logs",
        "handover_requests",
        "knowledge_versions",
        "quality_reports",
        "after_sales",
        "payments",
        "orders",
        "followup_tasks",
        "behavior_events",
        "message_dedup",
    ):
        op.drop_table(table)
