"""personal wechat reply reliability fields

Revision ID: 0009_reply_reliability
Revises: 0008_shared_module_tables
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_reply_reliability"
down_revision = "0008_shared_module_tables"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "personal_wechat_reply_tasks"
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    definitions = {
        "attempt_count": sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        "max_attempts": sa.Column(
            "max_attempts", sa.Integer(), nullable=False, server_default="3"
        ),
        "next_retry_at": sa.Column(
            "next_retry_at", sa.String(length=32), nullable=False, server_default=""
        ),
        "failure_code": sa.Column(
            "failure_code", sa.String(length=64), nullable=False, server_default=""
        ),
        "failure_stage": sa.Column(
            "failure_stage", sa.String(length=32), nullable=False, server_default=""
        ),
        "send_token": sa.Column(
            "send_token", sa.String(length=64), nullable=False, server_default=""
        ),
        "send_started_at": sa.Column(
            "send_started_at", sa.String(length=32), nullable=False, server_default=""
        ),
        "send_confirmed_at": sa.Column(
            "send_confirmed_at", sa.String(length=32), nullable=False, server_default=""
        ),
        "manual_review_at": sa.Column(
            "manual_review_at", sa.String(length=32), nullable=False, server_default=""
        ),
        "diagnostic_path": sa.Column(
            "diagnostic_path", sa.Text(), nullable=False, server_default=""
        ),
    }
    for name, column in definitions.items():
        if name not in columns:
            op.add_column(table_name, column)

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    index_definitions = {
        "ix_personal_wechat_reply_tasks_next_retry_at": ["next_retry_at"],
        "ix_personal_wechat_reply_tasks_failure_code": ["failure_code"],
        "ix_personal_wechat_reply_tasks_send_token": ["send_token"],
    }
    for name, columns in index_definitions.items():
        if name not in indexes:
            op.create_index(name, table_name, columns)


def downgrade():
    op.drop_index(
        "ix_personal_wechat_reply_tasks_send_token",
        table_name="personal_wechat_reply_tasks",
    )
    op.drop_index(
        "ix_personal_wechat_reply_tasks_failure_code",
        table_name="personal_wechat_reply_tasks",
    )
    op.drop_index(
        "ix_personal_wechat_reply_tasks_next_retry_at",
        table_name="personal_wechat_reply_tasks",
    )
    for column in (
        "diagnostic_path",
        "manual_review_at",
        "send_confirmed_at",
        "send_started_at",
        "send_token",
        "failure_stage",
        "failure_code",
        "next_retry_at",
        "max_attempts",
        "attempt_count",
    ):
        op.drop_column("personal_wechat_reply_tasks", column)
