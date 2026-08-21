"""add_judgment_agent_fields

Revision ID: c001_add_judgment_agent
Revises: 0b723c4f216b
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c001_add_judgment_agent'
down_revision: Union[str, None] = '0b723c4f216b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 工单表新增判断Agent相关字段
    op.add_column('work_orders', sa.Column(
        'judgment_status', sa.String(length=32), nullable=True,
        comment='None|pending_judge|judging|approved|rejected|no_action_needed|degraded'
    ))
    op.add_column('work_orders', sa.Column(
        'judgment_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
        comment='Agent返回的完整判定结果'
    ))
    op.add_column('work_orders', sa.Column(
        'judgment_requested_at', sa.DateTime(), nullable=True,
        comment='提交判断时间'
    ))
    op.add_column('work_orders', sa.Column(
        'judgment_completed_at', sa.DateTime(), nullable=True,
        comment='判断完成时间'
    ))

    # 回填增强：PMO建议的新工单参数
    op.add_column('work_orders', sa.Column(
        'triggered_wo_title', sa.String(length=256), nullable=True,
        comment='PMO建议的新工单标题'
    ))
    op.add_column('work_orders', sa.Column(
        'triggered_wo_deadline', sa.Date(), nullable=True,
        comment='PMO建议的截止时间'
    ))
    op.add_column('work_orders', sa.Column(
        'triggered_wo_person_name', sa.String(length=64), nullable=True,
        comment='PMO建议的责任人'
    ))

    # 判断Agent降级日志表
    op.create_table('judgment_degradation_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('work_order_id', sa.Integer(), nullable=False, comment='关联工单'),
        sa.Column('reason', sa.String(length=64), nullable=False, comment='timeout|unreachable|parse_error|server_error'),
        sa.Column('original_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='判断Agent降级记录',
    )
    op.create_index('idx_jdl_wo', 'judgment_degradation_log', ['work_order_id'])


def downgrade() -> None:
    op.drop_index('idx_jdl_wo', table_name='judgment_degradation_log')
    op.drop_table('judgment_degradation_log')
    op.drop_column('work_orders', 'triggered_wo_person_name')
    op.drop_column('work_orders', 'triggered_wo_deadline')
    op.drop_column('work_orders', 'triggered_wo_title')
    op.drop_column('work_orders', 'judgment_completed_at')
    op.drop_column('work_orders', 'judgment_requested_at')
    op.drop_column('work_orders', 'judgment_result')
    op.drop_column('work_orders', 'judgment_status')