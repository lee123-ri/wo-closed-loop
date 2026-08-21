"""add region to work_orders

Revision ID: f1e34c0af84e
Revises: b001_sop
Create Date: 2026-08-14 10:28:10.949020
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1e34c0af84e"
down_revision: Union[str, None] = "b001_sop"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("region", sa.String(length=16), nullable=True, comment="区域：华北/华中/华东/华南/西北/西南/东北"))


def downgrade() -> None:
    op.drop_column("work_orders", "region")