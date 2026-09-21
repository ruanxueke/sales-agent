"""add display_id columns

Revision ID: 0006_add_display_id
Revises: 0005_add_solda_modules
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_add_display_id"
down_revision = "0005_add_solda_modules"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("display_id", sa.String(128), server_default=""))
    op.add_column("leads", sa.Column("display_id", sa.String(128), server_default=""))
    op.create_index("ix_customers_display_id", "customers", ["display_id"])
    op.create_index("ix_leads_display_id", "leads", ["display_id"])


def downgrade():
    op.drop_index("ix_leads_display_id", table_name="leads")
    op.drop_index("ix_customers_display_id", table_name="customers")
    op.drop_column("leads", "display_id")
    op.drop_column("customers", "display_id")
