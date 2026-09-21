"""add leads table

Revision ID: 0002_add_leads
Revises: 0001_initial
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_leads"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(128), server_default=""),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(64), server_default=""),
        sa.Column("phone", sa.String(32), server_default=""),
        sa.Column("wechat_id", sa.String(128), server_default=""),
        sa.Column("unionid", sa.String(128), server_default=""),
        sa.Column("nickname", sa.String(128), server_default=""),
        sa.Column("source", sa.String(32), server_default="import"),
        sa.Column("channel_id", sa.String(64), server_default=""),
        sa.Column("identity", sa.String(32), server_default=""),
        sa.Column("level", sa.String(32), server_default=""),
        sa.Column("goal", sa.String(64), server_default=""),
        sa.Column("budget", sa.String(64), server_default=""),
        sa.Column("interest", sa.String(64), server_default=""),
        sa.Column("stage", sa.String(32), server_default="new"),
        sa.Column("intent_level", sa.String(32), server_default=""),
        sa.Column("intent_score", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(32), server_default="assigned"),
        sa.Column("owner", sa.String(64), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("next_follow_up", sa.String(32), server_default=""),
        sa.Column("assigned_at", sa.String(32), server_default=""),
        sa.Column("last_follow_at", sa.String(32), server_default=""),
        sa.Column("last_message_at", sa.String(32), server_default=""),
        sa.Column("sla_due_at", sa.String(32), server_default=""),
        sa.Column("recycled_at", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_leads_session_id", "leads", ["session_id"])
    op.create_index("ix_leads_customer_id", "leads", ["customer_id"])
    op.create_index("ix_leads_phone", "leads", ["phone"])
    op.create_index("ix_leads_wechat_id", "leads", ["wechat_id"])
    op.create_index("ix_leads_unionid", "leads", ["unionid"])
    op.create_index("ix_leads_source", "leads", ["source"])
    op.create_index("ix_leads_channel_id", "leads", ["channel_id"])
    op.create_index("ix_leads_status", "leads", ["status"])
    op.create_index("ix_leads_owner", "leads", ["owner"])


def downgrade():
    op.drop_table("leads")
