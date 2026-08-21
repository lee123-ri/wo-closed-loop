"""add no-dispatch close fields to work_orders

Revision ID: e001_add_no_dispatch
Revises: d003_add_pool_priority
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e001_add_no_dispatch'
down_revision: Union[str, None] = 'd003_add_pool_priority'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column(
        'closed_without_dispatch', sa.Boolean(), nullable=True,
        server_default=sa.text('false'),
        comment='是否不发现场直接关闭',
    ))
    op.add_column('work_orders', sa.Column(
        'no_dispatch_reason', sa.Text(), nullable=True,
        comment='不发现场关闭原因',
    ))
    op.add_column('work_orders', sa.Column(
        'no_dispatch_synced', sa.Boolean(), nullable=True,
        server_default=sa.text('false'),
        comment='关闭原因是否已写回AITable台账',
    ))


def downgrade() -> None:
    op.drop_column('work_orders', 'no_dispatch_synced')
    op.drop_column('work_orders', 'no_dispatch_reason')
    op.drop_column('work_orders', 'closed_without_dispatch')