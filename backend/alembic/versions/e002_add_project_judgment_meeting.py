"""add judgment-meeting fields to projects

Revision ID: e002_add_project_judgment_meeting
Revises: d003_add_pool_priority
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e002_add_project_judgment_meeting'
down_revision: Union[str, None] = 'd003_add_pool_priority'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('entry_date', sa.Date(), nullable=True, comment='入场日期'))
    op.add_column('projects', sa.Column('product_series', sa.String(length=32), nullable=True, comment='产品系列 HS100/HS200/HS300/HS400/HS500/500Pro'))
    op.add_column('projects', sa.Column('judgment_date', sa.Date(), nullable=True, comment='判定日 = 入场日期 + 判定天数 - 1'))
    op.add_column('projects', sa.Column('judgment_event_id', sa.String(length=128), nullable=True, comment='钉钉日历日程 eventId（幂等）'))
    op.add_column('projects', sa.Column('judgment_status', sa.String(length=32), nullable=True, comment='pending|created|failed'))
    op.add_column('projects', sa.Column('judgment_error', sa.String(length=512), nullable=True, comment='建会失败原因'))


def downgrade() -> None:
    op.drop_column('projects', 'judgment_error')
    op.drop_column('projects', 'judgment_status')
    op.drop_column('projects', 'judgment_event_id')
    op.drop_column('projects', 'judgment_date')
    op.drop_column('projects', 'product_series')
    op.drop_column('projects', 'entry_date')