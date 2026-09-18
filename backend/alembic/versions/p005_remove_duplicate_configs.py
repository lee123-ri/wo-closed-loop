"""remove duplicate regional and role-person configuration

Revision ID: p005_remove_duplicates
Revises: p004_simplify_roles
"""
import sqlalchemy as sa
from alembic import op


revision = "p005_remove_duplicates"
down_revision = "p004_simplify_roles"
branch_labels = None
depends_on = None


def upgrade():
    # 将旧“角色→人员”已配置的审批人写入工单类型的直接审批人字段，
    # 再删除重复的映射和已不再被页面消费的区域负责人表。
    op.execute("""
        UPDATE workorder_type_kb AS work_type
        SET default_approver_id = assignment.user_id
        FROM role_assignments AS assignment
        WHERE work_type.default_approver_id IS NULL
          AND work_type.default_approver_role = assignment.role_code
          AND assignment.user_id IS NOT NULL
    """)
    op.drop_column("workorder_type_kb", "default_approver_role")
    op.drop_table("region_pmos")
    op.drop_table("role_assignments")


def downgrade():
    op.create_table(
        "region_pmos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("region", sa.String(length=16), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "role_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("role_code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("role_name", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("workorder_type_kb", sa.Column("default_approver_role", sa.String(length=32), nullable=True))
