"""merge d003_add_pool_priority and d001_add_triggered_wo_tasks heads

两条分支（d001_add_region_pmo→d002→d003 与 d001_add_triggered_wo_tasks）
都以 c001_add_judgment_agent 为父导致双头，此合并迁移统一迁移链。

Revision ID: e001_merge_heads
Revises: d003_add_pool_priority, d001_add_triggered_wo_tasks
Create Date: 2026-09-02
"""
from typing import Union

# revision identifiers, used by Alembic.
revision: str = 'e001_merge_heads'
down_revision: Union[str, tuple, None] = ('d003_add_pool_priority', 'd001_add_triggered_wo_tasks')
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    pass


def downgrade():
    pass
