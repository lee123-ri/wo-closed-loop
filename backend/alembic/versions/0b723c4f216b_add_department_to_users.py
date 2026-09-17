"""add department to users

Revision ID: 0b723c4f216b
Revises: f1e34c0af84e
Create Date: 2026-08-14 11:15:24.664083
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0b723c4f216b"
down_revision: Union[str, None] = "f1e34c0af84e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("department", sa.String(length=128), nullable=True, comment="部门名称"))
    op.add_column("users", sa.Column("department_id", sa.String(length=32), nullable=True, comment="钉钉部门ID"))


def downgrade() -> None:
    op.drop_column("users", "department_id")
    op.drop_column("users", "department")