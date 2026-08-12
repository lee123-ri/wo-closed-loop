"""add dingtalk_group_id to projects

Revision ID: 0002_project_group
Revises: 0001_initial
Create Date: 2026-08-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_project_group"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("dingtalk_group_id", sa.String(128), comment="钉钉群 conversationId"))


def downgrade() -> None:
    op.drop_column("projects", "dingtalk_group_id")
