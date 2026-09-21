"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(128), nullable=False, unique=True),
        sa.Column("nickname", sa.String(128), server_default=""),
        sa.Column("source", sa.String(32), server_default="wechat"),
        sa.Column("name", sa.String(64), server_default=""),
        sa.Column("phone", sa.String(32), server_default=""),
        sa.Column("wechat_id", sa.String(128), server_default=""),
        sa.Column("identity", sa.String(32), server_default=""),
        sa.Column("level", sa.String(32), server_default=""),
        sa.Column("goal", sa.String(64), server_default=""),
        sa.Column("budget", sa.String(64), server_default=""),
        sa.Column("interest", sa.String(64), server_default=""),
        sa.Column("stage", sa.String(32), server_default="new"),
        sa.Column("intent_level", sa.String(32), server_default=""),
        sa.Column("intent_score", sa.Integer(), server_default="0"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("next_follow_up", sa.String(32), server_default=""),
        sa.Column("created_at", sa.String(32)),
        sa.Column("updated_at", sa.String(32)),
    )
    op.create_index("ix_customers_session_id", "customers", ["session_id"])
    op.create_table(
        "stage_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("from_stage", sa.String(32), server_default=""),
        sa.Column("to_stage", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(255), server_default=""),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_stage_log_customer_id", "stage_log", ["customer_id"])
    op.create_table(
        "customer_chat_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_customer_chat_log_customer_id", "customer_chat_log", ["customer_id"])
    op.create_table(
        "customer_chat_archive",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), server_default=""),
        sa.Column("archived_at", sa.String(32)),
    )
    op.create_index("ix_customer_chat_archive_customer_id", "customer_chat_archive", ["customer_id"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(128), server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("created_at", sa.String(32)),
    )
    op.create_index("ix_notifications_customer_id", "notifications", ["customer_id"])


def downgrade():
    op.drop_table("notifications")
    op.drop_table("customer_chat_archive")
    op.drop_table("customer_chat_log")
    op.drop_table("stage_log")
    op.drop_table("customers")
