"""add_triggered_wo_tasks

Revision ID: d001_add_triggered_wo_tasks
Revises: c001_add_judgment_agent
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd001_add_triggered_wo_tasks'
down_revision: Union[str, None] = 'c001_add_judgment_agent'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column(
        'triggered_wo_tasks', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
        comment='措施工单任务列表 [{title, person_name, deadline}]'
    ))


def downgrade() -> None:
    op.drop_column('work_orders', 'triggered_wo_tasks')