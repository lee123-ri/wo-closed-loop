"""add metric_type to work_orders

异常指标大类（source=alert 的细分维度），与 DataPoolItem.metric_type 对齐。
用于按类别匹配默认责任人、路由分析 Agent、以及后续「同项目+同指标大类」的复用/合并匹配。

Revision ID: h001_add_workorder_metric_type
Revises: g001_add_client_request_id
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "h001_add_workorder_metric_type"
down_revision: Union[str, None] = "g001_add_client_request_id"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column(
        'metric_type', sa.String(length=32), nullable=True,
        comment='异常指标大类 power_gen|curtailment|dual_rule|reliability|info_quality|contract|cost|satisfaction',
    ))


def downgrade() -> None:
    op.drop_column('work_orders', 'metric_type')