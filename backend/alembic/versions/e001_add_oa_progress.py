"""add oa_progress to work_orders

Revision ID: e001_add_oa_progress
Revises: d003_add_pool_priority
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e001_add_oa_progress'
down_revision: Union[str, None] = 'd003_add_pool_priority'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column(
        'oa_progress', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
        comment='OA审批进度 [{stage,role,title,user_id,dingtalk_id,approved}]',
    ))


def downgrade() -> None:
    op.drop_column('work_orders', 'oa_progress')