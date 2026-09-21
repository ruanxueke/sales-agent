"""commercial hardening: tenant scope, RBAC service keys, pgvector knowledge

Revision ID: 0010_commercial_hardening
Revises: 0009_reply_reliability
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_commercial_hardening"
down_revision = "0009_reply_reliability"
branch_labels = None
depends_on = None


TENANT_TABLES = {
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
    "knowledge_versions",
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
    "alert_rules",
    "alert_events",
    "approval_rules",
    "commission_records",
    "commission_rules",
    "consent_logs",
    "customer_tiers",
    "deletion_requests",
    "llm_traces",
    "llm_usage",
    "knowledge_gaps",
    "sales_targets",
    "sla_policies",
    "usage_ledger",
    "webchat_messages",
    "webchat_sessions",
}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def _add_tenant_column(table: str) -> None:
    if table not in _table_names() or "tenant_id" in _columns(table):
        return
    op.add_column(
        table,
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    index_name = f"ix_{table}_tenant_id"
    if index_name not in _indexes(table):
        op.create_index(index_name, table, ["tenant_id"])


def _create_knowledge_and_security_tables() -> None:
    names = _table_names()

    if "knowledge_documents" not in names:
        op.create_table(
            "knowledge_documents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("filename", sa.String(255), nullable=False, server_default=""),
            sa.Column("source_path", sa.Text(), nullable=False, server_default=""),
            sa.Column("file_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
            sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
        )
        op.create_index("ix_knowledge_documents_tenant_id", "knowledge_documents", ["tenant_id"])
        op.create_index("ix_knowledge_documents_filename", "knowledge_documents", ["filename"])
        op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
        op.create_index("ix_knowledge_documents_active", "knowledge_documents", ["active"])

    if "knowledge_index_versions" not in names:
        op.create_table(
            "knowledge_index_versions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("version_name", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="building"),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
            sa.Column("activated_at", sa.String(32), nullable=False, server_default=""),
            sa.Column("retired_at", sa.String(32), nullable=False, server_default=""),
        )
        op.create_index(
            "ix_knowledge_index_versions_tenant_id",
            "knowledge_index_versions",
            ["tenant_id"],
        )
        op.create_index(
            "ix_knowledge_index_versions_status",
            "knowledge_index_versions",
            ["status"],
        )

    if "knowledge_chunks" not in names:
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("document_id", sa.Integer(), nullable=True),
            sa.Column("index_version_id", sa.Integer(), nullable=True),
            sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("embedding_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        )
        op.create_index("ix_knowledge_chunks_tenant_id", "knowledge_chunks", ["tenant_id"])
        op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
        op.create_index(
            "ix_knowledge_chunks_index_version_id",
            "knowledge_chunks",
            ["index_version_id"],
        )

    if "api_key_accounts" not in names:
        op.create_table(
            "api_key_accounts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("name", sa.String(128), nullable=False, server_default=""),
            sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
            sa.Column("role", sa.String(32), nullable=False, server_default="service"),
            sa.Column("scopes_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("expires_at", sa.String(32), nullable=False, server_default=""),
            sa.Column("last_used_at", sa.String(32), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
            sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        )
        op.create_index("ix_api_key_accounts_tenant_id", "api_key_accounts", ["tenant_id"])
        op.create_index("ix_api_key_accounts_key_hash", "api_key_accounts", ["key_hash"])
        op.create_index("ix_api_key_accounts_status", "api_key_accounts", ["status"])


def upgrade() -> None:
    for table in sorted(TENANT_TABLES):
        _add_tenant_column(table)

    _create_knowledge_and_security_tables()

    if "knowledge_versions" in _table_names():
        columns = _columns("knowledge_versions")
        if "document_id" not in columns:
            op.add_column("knowledge_versions", sa.Column("document_id", sa.Integer(), nullable=True))
        if "index_version_id" not in columns:
            op.add_column(
                "knowledge_versions",
                sa.Column("index_version_id", sa.Integer(), nullable=True),
            )

    if "deletion_requests" in _table_names():
        columns = _columns("deletion_requests")
        additions = {
            "error": sa.Column("error", sa.Text(), nullable=False, server_default=""),
            "result_json": sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
            "attempts": sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            "next_retry_at": sa.Column(
                "next_retry_at",
                sa.String(32),
                nullable=False,
                server_default="",
            ),
        }
        for name, column in additions.items():
            if name not in columns:
                op.add_column("deletion_requests", column)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        if "embedding_vector" not in _columns("knowledge_chunks"):
            op.execute("ALTER TABLE knowledge_chunks ADD COLUMN embedding_vector vector")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_tenant_version "
            "ON knowledge_chunks (tenant_id, index_version_id)"
        )

    # 旧数据默认归到默认租户；新数据由应用层显式写入 tenant_id。
    if bind.dialect.name == "postgresql":
        op.execute("UPDATE customers SET tenant_id = 0 WHERE tenant_id IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_tenant_version")
    for table in (
        "api_key_accounts",
        "knowledge_chunks",
        "knowledge_index_versions",
        "knowledge_documents",
    ):
        if table in _table_names():
            op.drop_table(table)
    for table in sorted(TENANT_TABLES):
        if table not in _table_names() or "tenant_id" not in _columns(table):
            continue
        index_name = f"ix_{table}_tenant_id"
        if index_name in _indexes(table):
            op.drop_index(index_name, table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("tenant_id")
