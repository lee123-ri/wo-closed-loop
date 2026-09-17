"""add role_assignments table + default_approver_role

Revision ID: d002_add_role_assignments
Revises: d001_add_region_pmo
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd002_add_role_assignments'
down_revision: Union[str, None] = 'd001_add_region_pmo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('role_assignments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('role_code', sa.String(length=32), nullable=False, comment='division_head|pmo|delivery_pmo'),
        sa.Column('role_name', sa.String(length=64), nullable=True, comment='事业部负责人/事业部PMO/交付PMO'),
        sa.Column('user_id', sa.Integer(), nullable=True, comment='担任该角色的人员ID'),
        sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_code'),
        comment='组织角色-人员映射',
    )
    op.add_column('workorder_type_kb', sa.Column(
        'default_approver_role', sa.String(length=32), nullable=True,
        comment='默认审批人角色编码，如 division_head/pmo/delivery_pmo',
    ))


def downgrade() -> None:
    op.drop_column('workorder_type_kb', 'default_approver_role')
    op.drop_table('role_assignments')