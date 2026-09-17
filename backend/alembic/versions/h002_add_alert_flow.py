"""add alert flow: alert_phase column + measure link (many-to-many) + anomaly occurrence

监视告警(alert)五阶段闭环的地基：
- work_orders.alert_phase：confirming|dispatching|tracking|reexamining|recovered（非alert为None）
- work_order_measure_links：异常主单↔措施工单 多对多（复用/挂载、2/11 进度）
- anomaly_occurrences：异常主单的发生记录（合并/多月复用，供指标复核看历史发生次数）

Revision ID: h002_add_alert_flow
Revises: h001_add_workorder_metric_type
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "h002_add_alert_flow"
down_revision: Union[str, None] = "h001_add_workorder_metric_type"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column(
        'alert_phase', sa.String(length=32), nullable=True,
        comment='alert 五阶段：confirming|dispatching|tracking|reexamining|recovered（非alert为None）',
    ))

    op.create_table(
        'work_order_measure_links',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('host_wo_id', sa.Integer(), sa.ForeignKey('work_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('measure_wo_id', sa.Integer(), sa.ForeignKey('work_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('link_source', sa.String(length=16), nullable=True),
        sa.Column('removed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_work_order_measure_links_host_wo_id', 'work_order_measure_links', ['host_wo_id'])
    op.create_index('ix_work_order_measure_links_measure_wo_id', 'work_order_measure_links', ['measure_wo_id'])

    op.create_table(
        'anomaly_occurrences',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('host_wo_id', sa.Integer(), sa.ForeignKey('work_orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('occurred_at', sa.Date(), nullable=True),
        sa.Column('metric_type', sa.String(length=32), nullable=True),
        sa.Column('indicator_type', sa.String(length=128), nullable=True),
        sa.Column('pool_item_id', sa.Integer(), sa.ForeignKey('data_pool_items.id'), nullable=True),
        sa.Column('note', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_anomaly_occurrences_host_wo_id', 'anomaly_occurrences', ['host_wo_id'])


def downgrade() -> None:
    op.drop_index('ix_anomaly_occurrences_host_wo_id', table_name='anomaly_occurrences')
    op.drop_table('anomaly_occurrences')
    op.drop_index('ix_work_order_measure_links_measure_wo_id', table_name='work_order_measure_links')
    op.drop_index('ix_work_order_measure_links_host_wo_id', table_name='work_order_measure_links')
    op.drop_table('work_order_measure_links')
    op.drop_column('work_orders', 'alert_phase')