"""add client_request_id to work_orders

外部建单 API 的幂等去重字段：调用方传入的唯一请求标识（如 trace_id / 业务单号）。
同一 client_request_id 重复提交时，接口返回首次创建的那条工单，不重复建单。

Revision ID: g001_add_client_request_id
Revises: f001_normalize_project_codes
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "g001_add_client_request_id"
down_revision: Union[str, None] = "f001_normalize_project_codes"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column(
        'client_request_id', sa.String(length=64), nullable=True,
        comment='外部 API 调用方请求唯一标识（幂等去重）',
    ))
    op.create_index(
        'ix_work_orders_client_request_id',
        'work_orders', ['client_request_id'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_work_orders_client_request_id', table_name='work_orders')
    op.drop_column('work_orders', 'client_request_id')