"""add task_deliverable to work_orders

年度运营计划工单新增「任务目标交付物」字段（计划类进列表必填）。
它描述闭环时必须上传的附件/成果，用于在 OA 表单、详情页、列表展开项和导入错误报告中
提醒「该传什么附件才能闭环任务」。其他来源(manual/alert/meeting/external)不强制。

Revision ID: i001_add_task_deliverable
Revises: h002_add_alert_flow
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "i001_add_task_deliverable"
down_revision: Union[str, None] = "h002_add_alert_flow"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column(
        'task_deliverable', sa.Text(), nullable=True,
        comment='任务目标交付物（年度计划类必填）',
    ))


def downgrade() -> None:
    op.drop_column('work_orders', 'task_deliverable')