"""add service field to work orders

Revision ID: l001_add_work_order_service
Revises: k001_add_role_data_scopes
"""
from alembic import op
import sqlalchemy as sa

revision = "l001_add_work_order_service"
down_revision = "k001_add_role_data_scopes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work_orders", sa.Column("service", sa.String(length=128), nullable=True))


def downgrade():
    op.drop_column("work_orders", "service")
