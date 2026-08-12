"""add_data_pool_and_backfill

Revision ID: a001_add_data_pool_backfill
Revises: 001
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a001_add_data_pool_backfill'
down_revision: Union[str, None] = '0002_project_group'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 数据池
    op.create_table('data_pool_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('pool_type', sa.String(length=16), nullable=False, comment='plan|anomaly'),
        sa.Column('source_system', sa.String(length=32), server_default='manual', nullable=False),
        sa.Column('source_ref', sa.String(length=256), nullable=True),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('project_name', sa.String(length=128), nullable=True),
        sa.Column('person_name', sa.String(length=64), nullable=True),
        sa.Column('deadline', sa.Date(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('metric_type', sa.String(length=32), nullable=True),
        sa.Column('metric_value', sa.Float(), nullable=True),
        sa.Column('threshold', sa.Float(), nullable=True),
        sa.Column('deviation_pct', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('work_order_id', sa.Integer(), nullable=True),
        sa.Column('skip_reason', sa.String(length=256), nullable=True),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('backfill_reason', sa.Text(), nullable=True),
        sa.Column('backfill_action', sa.Text(), nullable=True),
        sa.Column('backfilled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='数据池-暂存待生成工单的原始数据',
    )

    # 工单扩展字段
    op.add_column('work_orders', sa.Column('backfill_status', sa.String(length=16), nullable=True, comment='pending|filled'))
    op.add_column('work_orders', sa.Column('backfill_reason', sa.Text(), nullable=True, comment='责任人填写的根因分析'))
    op.add_column('work_orders', sa.Column('backfill_action', sa.Text(), nullable=True, comment='责任人填写的应对措施'))
    op.add_column('work_orders', sa.Column('backfilled_at', sa.DateTime(), nullable=True, comment='回填时间'))
    op.add_column('work_orders', sa.Column('parent_pool_id', sa.Integer(), nullable=True, comment='来源数据池记录'))
    op.add_column('work_orders', sa.Column('triggered_wo_id', sa.Integer(), nullable=True, comment='回填后触发的新工单'))

    op.create_foreign_key('fk_wo_parent_pool', 'work_orders', 'data_pool_items', ['parent_pool_id'], ['id'])
    op.create_foreign_key('fk_wo_triggered', 'work_orders', 'work_orders', ['triggered_wo_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_wo_triggered', 'work_orders', type_='foreignkey')
    op.drop_constraint('fk_wo_parent_pool', 'work_orders', type_='foreignkey')
    op.drop_column('work_orders', 'triggered_wo_id')
    op.drop_column('work_orders', 'parent_pool_id')
    op.drop_column('work_orders', 'backfilled_at')
    op.drop_column('work_orders', 'backfill_action')
    op.drop_column('work_orders', 'backfill_reason')
    op.drop_column('work_orders', 'backfill_status')
    op.drop_table('data_pool_items')