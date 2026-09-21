"""add solda modules: ammo, case, conversation summary, winning, engagement, optimization, compliance

Revision ID: 0005_add_solda_modules
Revises: 0004_add_business_modules
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_add_solda_modules"
down_revision = "0004_add_business_modules"
branch_labels = None
depends_on = None


def _col(name, typ, default=""):
    return sa.Column(name, typ, server_default=default)


def _cols(spec):
    out = []
    for name, kind, default in spec:
        out.append(_col(name, kind, default))
    return out


def upgrade():
    op.add_column("customers", sa.Column("sales_status", sa.String(32), server_default="new_lead"))
    op.add_column("leads", sa.Column("sales_status", sa.String(32), server_default="new_lead"))
    op.add_column("followup_tasks", sa.Column("result", sa.String(32), server_default=""))
    op.add_column("followup_tasks", sa.Column("source_script_id", sa.Integer(), nullable=True))

    S = sa.String
    T = sa.Text
    I = sa.Integer
    F = sa.Float
    B = sa.Boolean

    tables = [
        ("sales_cases", [
            ("title", S(255), ""), ("case_type", S(32), "general"), ("source", S(32), "manual"),
            ("channel", S(32), ""), ("content", T(), ""), ("key_turns", T(), ""),
            ("objections", T(), ""), ("winning_points", T(), ""), ("mistakes", T(), ""),
            ("result", S(32), ""), ("tags", S(255), ""), ("active", B(), "1"),
            ("created_at", S(32), ""), ("updated_at", S(32), ""),
        ]),
        ("product_knowledge", [
            ("product_name", S(128), ""), ("target_customer", S(255), ""), ("solves", T(), ""),
            ("selling_points", T(), ""), ("price", S(64), ""), ("after_sales", T(), ""),
            ("risk_limits", T(), ""), ("proof", T(), ""), ("active", B(), "1"),
            ("created_at", S(32), ""), ("updated_at", S(32), ""),
        ]),
        ("objection_responses", [
            ("trigger_scene", S(255), ""), ("standard_reply", T(), ""), ("evidence", T(), ""),
            ("next_step", T(), ""), ("active", B(), "1"), ("sort", I(), "0"), ("created_at", S(32), ""),
        ]),
        ("competitor_responses", [
            ("competitor", S(128), ""), ("customer_saying", S(255), ""),
            ("differentiator_1", S(255), ""), ("differentiator_2", S(255), ""),
            ("differentiator_3", S(255), ""), ("standard_reply", T(), ""), ("active", B(), "1"),
            ("created_at", S(32), ""),
        ]),
        ("followup_scripts", [
            ("followup_scene", S(128), ""), ("trigger_condition", S(255), ""), ("value_point", T(), ""),
            ("script_example", T(), ""), ("next_goal", T(), ""), ("delay_hours", I(), "24"),
            ("active", B(), "1"), ("created_at", S(32), ""),
        ]),
        ("conversation_summary", [
            ("session_id", S(128), ""), ("customer_id", I(), "0"), ("lead_id", I(), "0"),
            ("source", S(32), ""), ("sales_status", S(32), "new_lead"), ("core_concern", S(255), ""),
            ("selection_criteria", S(255), ""), ("evidence_given", S(255), ""),
            ("next_follow_time", S(32), ""), ("next_follow_reason", S(255), ""),
            ("next_goal", S(255), ""), ("raw_json", T(), ""), ("created_at", S(32), ""),
        ]),
        ("differentiators", [
            ("product", S(128), ""), ("differentiator", S(255), ""), ("evidence", T(), ""),
            ("customer_concern", S(128), ""), ("active", B(), "1"), ("created_at", S(32), ""),
        ]),
        ("evidence_library", [
            ("evidence_type", S(32), "case"), ("title", S(255), ""), ("content", T(), ""),
            ("link", S(255), ""), ("scenario", S(255), ""), ("active", B(), "1"),
            ("created_at", S(32), ""),
        ]),
        ("key_moment_tools", [
            ("tool_type", S(32), "trial"), ("name", S(128), ""), ("description", T(), ""),
            ("trigger_scene", S(255), ""), ("active", B(), "1"), ("created_at", S(32), ""),
        ]),
        ("appointments", [
            ("session_id", S(128), ""), ("customer_id", I(), "0"), ("lead_id", I(), "0"),
            ("order_id", I(), "0"), ("appointment_type", S(32), "trial"), ("title", S(255), ""),
            ("start_at", S(32), ""), ("end_at", S(32), ""), ("status", S(32), "pending"),
            ("owner", S(64), ""), ("note", T(), ""), ("created_at", S(32), ""),
            ("updated_at", S(32), ""),
        ]),
        ("coupons", [
            ("name", S(128), ""), ("coupon_type", S(32), "discount"), ("value", S(64), ""),
            ("min_amount", F(), "0"), ("valid_days", I(), "7"), ("quota", I(), "0"),
            ("status", S(32), "active"), ("created_at", S(32), ""), ("updated_at", S(32), ""),
        ]),
        ("user_coupons", [
            ("coupon_id", I(), "0"), ("session_id", S(128), ""), ("customer_id", I(), "0"),
            ("lead_id", I(), "0"), ("status", S(32), "unused"), ("expires_at", S(32), ""),
            ("used_at", S(32), ""), ("order_id", I(), "0"), ("created_at", S(32), ""),
        ]),
        ("payment_links", [
            ("order_id", I(), "0"), ("session_id", S(128), ""), ("customer_id", I(), "0"),
            ("lead_id", I(), "0"), ("title", S(255), ""), ("amount", F(), "0"),
            ("pay_method", S(32), "wechat"), ("link", S(255), ""), ("qr_text", T(), ""),
            ("status", S(32), "pending"), ("expires_at", S(32), ""), ("created_at", S(32), ""),
        ]),
        ("conversation_metrics", [
            ("session_id", S(128), ""), ("customer_id", I(), "0"), ("lead_id", I(), "0"),
            ("source", S(32), ""), ("stage", S(32), ""), ("sales_status", S(32), ""),
            ("core_concern", S(255), ""), ("competitor_mentioned", S(128), ""),
            ("emotion", S(32), ""), ("has_next_step", B(), "0"), ("gave_evidence", B(), "0"),
            ("bound_differentiator", B(), "0"), ("is_deal", B(), "0"), ("followup_result", S(32), ""),
            ("lost_reason", S(255), ""), ("created_at", S(32), ""),
        ]),
        ("ab_experiments", [
            ("name", S(128), ""), ("kind", S(32), "script"), ("control", T(), ""),
            ("variant", T(), ""), ("status", S(32), "draft"), ("start_at", S(32), ""),
            ("end_at", S(32), ""), ("note", T(), ""), ("created_at", S(32), ""),
        ]),
        ("ab_runs", [
            ("experiment_id", I(), "0"), ("session_id", S(128), ""), ("variant", S(32), "control"),
            ("result", S(32), ""), ("created_at", S(32), ""),
        ]),
        ("weekly_reviews", [
            ("week_start", S(16), ""), ("content", T(), ""), ("metrics_json", T(), "{}"),
            ("created_at", S(32), ""),
        ]),
        ("compliance_rules", [
            ("rule_type", S(32), "handover"), ("trigger_words", T(), ""), ("action", S(32), "handover"),
            ("priority", I(), "0"), ("enabled", B(), "1"), ("description", T(), ""),
            ("created_at", S(32), ""),
        ]),
    ]

    for table, spec in tables:
        op.create_table(table, sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), *_cols(spec))

    index_map = {
        "sales_cases": ["case_type"],
        "product_knowledge": ["product_name"],
        "objection_responses": ["trigger_scene"],
        "competitor_responses": ["competitor"],
        "followup_scripts": ["followup_scene"],
        "conversation_summary": ["session_id", "customer_id", "lead_id", "sales_status"],
        "evidence_library": ["evidence_type"],
        "key_moment_tools": ["tool_type"],
        "appointments": ["session_id", "customer_id", "start_at", "status"],
        "coupons": ["coupon_type", "status"],
        "user_coupons": ["coupon_id", "session_id", "customer_id", "status"],
        "payment_links": ["order_id", "session_id", "status"],
        "conversation_metrics": ["session_id", "customer_id", "sales_status"],
        "ab_experiments": ["name", "kind", "status"],
        "ab_runs": ["experiment_id", "session_id"],
        "weekly_reviews": ["week_start"],
        "compliance_rules": ["rule_type"],
    }
    for table, cols in index_map.items():
        for col in cols:
            op.create_index(f"ix_{table}_{col}", table, [col])
    op.create_index("ix_customers_sales_status", "customers", ["sales_status"])


def downgrade():
    tables = [
        "compliance_rules", "weekly_reviews", "ab_runs", "ab_experiments", "conversation_metrics",
        "payment_links", "user_coupons", "coupons", "appointments", "key_moment_tools",
        "evidence_library", "differentiators", "conversation_summary", "followup_scripts",
        "competitor_responses", "objection_responses", "product_knowledge", "sales_cases",
    ]
    for table in tables:
        op.drop_table(table)
    op.drop_column("followup_tasks", "source_script_id")
    op.drop_column("followup_tasks", "result")
    op.drop_column("customers", "sales_status")
