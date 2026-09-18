"""add unified role center

Revision ID: n001_add_unified_role_center
Revises: l001_add_work_order_service
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "n001_add_unified_role_center"
down_revision = "l001_add_work_order_service"
branch_labels = None
depends_on = None


def _columns(*columns):
    return [*columns, sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False)]


def _create_if_missing(name, *columns):
    """兼容历史 Base.metadata.create_all 已建表、但未写 Alembic 版本的本地库。"""
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns)


def upgrade():
    _create_if_missing("permission_roles", *_columns(
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False), sa.Column("data_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("menu_permissions", postgresql.JSONB(), nullable=False), sa.Column("action_permissions", postgresql.JSONB(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False), sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False)))
    _create_if_missing("user_permission_roles", *_columns(
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_role_id", sa.Integer(), sa.ForeignKey("permission_roles.id", ondelete="CASCADE"), nullable=False), sa.UniqueConstraint("user_id", "permission_role_id")))
    _create_if_missing("business_roles", *_columns(
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(64), unique=True, nullable=False), sa.Column("name", sa.String(64), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="global"), sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False), sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False)))
    _create_if_missing("business_role_assignments", *_columns(
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("business_role_id", sa.Integer(), sa.ForeignKey("business_roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="global"), sa.Column("scope_id", sa.Integer()), sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.UniqueConstraint("user_id", "business_role_id", "scope_type", "scope_id")))
    _create_if_missing("organization_sync_candidates", *_columns(
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("business_role_code", sa.String(64), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="global"), sa.Column("scope_id", sa.Integer()), sa.Column("source_kind", sa.String(32), nullable=False), sa.Column("source_value", sa.Text(), nullable=False), sa.Column("confidence", sa.Integer(), nullable=False, server_default="100"), sa.Column("status", sa.String(16), nullable=False, server_default="pending")))
    _create_if_missing("organization_mapping_rules", *_columns(
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(64), nullable=False), sa.Column("source_kind", sa.String(32), nullable=False), sa.Column("pattern", sa.String(256), nullable=False), sa.Column("business_role_code", sa.String(64), nullable=False), sa.Column("scope_type", sa.String(16), nullable=False, server_default="global"), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true"))))
    _create_if_missing("notification_rules", *_columns(
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(128), nullable=False), sa.Column("event", sa.String(64), nullable=False), sa.Column("conditions", postgresql.JSONB()), sa.Column("recipients", postgresql.JSONB(), nullable=False), sa.Column("channels", postgresql.JSONB(), nullable=False), sa.Column("template", sa.Text()), sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))))
    _create_if_missing("operation_events", *_columns(
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("category", sa.String(32), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("summary", sa.String(256), nullable=False), sa.Column("detail", postgresql.JSONB()), sa.Column("trace_id", sa.String(64)), sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id", ondelete="SET NULL")), sa.Column("notification_rule_id", sa.Integer(), sa.ForeignKey("notification_rules.id", ondelete="SET NULL"))))


def downgrade():
    for table in ("operation_events", "notification_rules", "organization_mapping_rules", "organization_sync_candidates", "business_role_assignments", "business_roles", "user_permission_roles", "permission_roles"):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
