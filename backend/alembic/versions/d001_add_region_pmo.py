"""add_region_pmo_table

Revision ID: d001_add_region_pmo
Revises: c001_add_judgment_agent
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd001_add_region_pmo'
down_revision: Union[str, None] = 'c001_add_judgment_agent'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('region_pmos',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('region', sa.String(length=16), nullable=False, comment='华北/华中/华东/华南/西北/西南/东北'),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户ID'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('region'),
        comment='区域PMO映射',
    )


def downgrade() -> None:
    op.drop_table('region_pmos')