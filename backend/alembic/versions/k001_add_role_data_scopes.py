"""add role_data_scopes table + 种子默认范围

把「谁能看哪些工单」从 scope.py 里的硬编码规则迁移到可后台配置的
role_data_scopes 表：admin/事业部PMO/区域PMO/普通成员 四个数据范围角色，
每个角色多选可见范围（self=自己相关 / region=区域 / all=全部），取并集去重。

默认值对齐旧硬编码行为（admin=全部 锁定、区域PMO=自己相关+区域、其他=自己相关），
事业部PMO 新增为「全部（可后台改）」。

Revision ID: k001_add_role_data_scopes
Revises: j001_unify_work_order_type
Create Date: 2026-09-17
"""
import json
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "k001_add_role_data_scopes"
down_revision: Union[str, None] = "j001_unify_work_order_type"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

# (role_code, role_name, scopes, is_locked, sort_order)
_SEED = [
    ("admin", "系统管理员", ["all"], True, 0),
    ("division_pmo", "事业部PMO", ["all"], False, 1),
    ("region_pmo", "区域PMO", ["self", "region"], False, 2),
    ("member", "普通成员", ["self"], False, 3),
]


def upgrade() -> None:
    op.create_table(
        "role_data_scopes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("role_code", sa.String(length=32), nullable=False, comment="admin|division_pmo|region_pmo|member"),
        sa.Column("role_name", sa.String(length=64), nullable=True, comment="系统管理员/事业部PMO/区域PMO/普通成员"),
        sa.Column("scopes", sa.dialects.postgresql.JSONB(), nullable=True, comment="['self','region','all'] 子集，多选取并集"),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("false"), comment="true=锁定不可后台改"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_code"),
        comment="角色数据范围配置",
    )

    bind = op.get_bind()
    for role_code, role_name, scopes, is_locked, sort_order in _SEED:
        bind.execute(
            sa.text("""
                INSERT INTO role_data_scopes (role_code, role_name, scopes, is_locked, sort_order)
                VALUES (:role_code, :role_name, CAST(:scopes AS jsonb), :is_locked, :sort_order)
                ON CONFLICT (role_code) DO NOTHING
            """),
            {
                "role_code": role_code,
                "role_name": role_name,
                "scopes": json.dumps(scopes, ensure_ascii=False),
                "is_locked": is_locked,
                "sort_order": sort_order,
            },
        )


def downgrade() -> None:
    op.drop_table("role_data_scopes")