"""remove retired rule data

Revision ID: p006_remove_legacy
Revises: p005_remove_duplicates
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "p006_remove_legacy"
down_revision = "p005_remove_duplicates"
branch_labels = None
depends_on = None


def upgrade():
    # 仅业务岗位的数据范围仍会被消费；旧身份派生行不会再生效，避免留下第二套配置。
    op.execute("""
        DELETE FROM role_data_scopes
        WHERE role_code NOT IN (SELECT code FROM business_roles)
    """)
    # 历史通知策略含电话、应用消息等已弃用通道；统一由 notification_rules 管理机器人私聊/群聊。
    op.drop_table("notification_policies")


def downgrade():
    op.create_table(
        "notification_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("channels", postgresql.JSONB(), nullable=False),
        sa.Column("template", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
