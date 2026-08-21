"""add priority to data_pool_items

Revision ID: d003_add_pool_priority
Revises: d002_add_role_assignments
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd003_add_pool_priority'
down_revision: Union[str, None] = 'd002_add_role_assignments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('data_pool_items', sa.Column(
        'priority', sa.String(length=16), nullable=True,
        comment='计划类自带优先级 P1|P2|P3；异常指标固定P1',
    ))


def downgrade() -> None:
    op.drop_column('data_pool_items', 'priority')