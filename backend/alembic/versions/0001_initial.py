"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, comment="姓名"),
        sa.Column("dingtalk_id", sa.String(128), comment="钉钉 unionId/userId"),
        sa.Column("phone", sa.String(32)),
        sa.Column("email", sa.String(128)),
        sa.Column("role", sa.String(32), nullable=False, server_default="executor", comment="admin|approver|executor|readonly"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("password_hash", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="用户（责任人/审批人/管理员）",
    )

    # projects
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), unique=True, nullable=False, comment="项目编码"),
        sa.Column("name", sa.String(128), nullable=False, comment="项目名称"),
        sa.Column("type", sa.String(32), comment="wind|pv|storage"),
        sa.Column("region", sa.String(64), comment="区域"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="电站项目",
    )

    # config_definitions
    op.create_table(
        "config_definitions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(32), nullable=False, index=True, comment="source|status|workorder_type|priority"),
        sa.Column("code", sa.String(64), nullable=False, comment="编码"),
        sa.Column("name", sa.String(128), nullable=False, comment="显示名"),
        sa.Column("color", sa.String(32)),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("extra", postgresql.JSONB, comment="扩展字段"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="配置定义（来源/状态/工单类型等）",
    )

    # workorder_type_kb （须在 work_orders 之前，因后者外键引用）
    op.create_table(
        "workorder_type_kb",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("type_code", sa.String(64), nullable=False, comment="类型编码"),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("desc", sa.Text),
        sa.Column("default_approver_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("default_priority", sa.String(16), nullable=False, server_default="P2"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="工单类型知识库",
    )

    # work_orders
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), unique=True, nullable=False, comment="RW-2026-0001"),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("reason", sa.Text, comment="触发原因"),
        sa.Column("action", sa.Text, comment="行动要求"),
        sa.Column("conclusion", sa.Text, comment="执行结论"),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id")),
        sa.Column("person_id", sa.Integer, sa.ForeignKey("users.id"), comment="责任人"),
        sa.Column("approver_id", sa.Integer, sa.ForeignKey("users.id"), comment="审批人"),
        sa.Column("type_id", sa.Integer, sa.ForeignKey("workorder_type_kb.id"), comment="工单类型"),
        sa.Column("source_code", sa.String(32), nullable=False, comment="来源 code"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending", comment="状态 code"),
        sa.Column("priority", sa.String(32), nullable=False, server_default="P2", comment="P1|P2|P3"),
        sa.Column("created_date", sa.Date, nullable=False, comment="工单创建日（业务日）"),
        sa.Column("deadline", sa.Date),
        sa.Column("completed_date", sa.Date),
        sa.Column("oa_id", sa.String(64), comment="钉钉 OA 审批单号"),
        sa.Column("escalation_level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("overdue_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="工单主表",
    )
    op.create_index("ix_work_orders_status", "work_orders", ["status"])
    op.create_index("ix_work_orders_priority", "work_orders", ["priority"])
    op.create_index("ix_work_orders_project_id", "work_orders", ["project_id"])

    # status_log
    op.create_table(
        "status_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("work_order_id", sa.Integer, sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="工单状态流转日志",
    )

    # attachments
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("work_order_id", sa.Integer, sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("oss_key", sa.String(512), nullable=False, comment="OSS 对象 key"),
        sa.Column("size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("uploader_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="工单佐证附件",
    )

    # escalation_log
    op.create_table(
        "escalation_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("work_order_id", sa.Integer, sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("level", sa.Integer, nullable=False, comment="升级到第几级"),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, comment="触发时间"),
        sa.Column("target", sa.String(128), comment="升级目标人"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="升级记录",
    )

    # notification_log
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("work_order_id", sa.Integer, sa.ForeignKey("work_orders.id", ondelete="CASCADE"), index=True),
        sa.Column("channel", sa.String(32), nullable=False, comment="ding|robot|sms|phone"),
        sa.Column("recipient", sa.String(128), nullable=False),
        sa.Column("event", sa.String(64), nullable=False, comment="dispatch|unread|sla_warn|sla_breach|sla_breach_72h"),
        sa.Column("status", sa.String(16), nullable=False, server_default="sent", comment="sent|failed"),
        sa.Column("message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="通知发送记录",
    )

    # person_project_map
    op.create_table(
        "person_project_map",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="人员-项目映射",
    )

    # priority_rules
    op.create_table(
        "priority_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("pattern", sa.String(512), nullable=False, comment="正则表达式"),
        sa.Column("label", sa.String(128), nullable=False, comment="规则说明"),
        sa.Column("priority", sa.String(16), nullable=False, comment="P1|P2|P3"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="优先级判定规则",
    )

    # parsing_rules
    op.create_table(
        "parsing_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("pattern", sa.String(512), nullable=False, comment="正则表达式"),
        sa.Column("weight", sa.Integer, nullable=False, server_default="1", comment="权重 1-5"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="听记解析规则",
    )

    # sla_definitions
    op.create_table(
        "sla_definitions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("priority", sa.String(16), unique=True, nullable=False, comment="P1|P2|P3"),
        sa.Column("deadline_days", sa.Integer, nullable=False, comment="截止天数"),
        sa.Column("warn_before_hours", sa.Integer, nullable=False, comment="到期前预警小时数"),
        sa.Column("escalate_hours", sa.Float, nullable=False, comment="违约后升级小时数"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="SLA 定义",
    )

    # approval_flows
    op.create_table(
        "approval_flows",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("priority", sa.String(16), nullable=False, comment="P1|P2|P3"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("nodes", postgresql.JSONB, nullable=False, comment="节点列表"),
        sa.Column("escalation", postgresql.JSONB, comment="{timeout_hours,action,target}"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="审批流模板",
    )

    # notification_policies
    op.create_table(
        "notification_policies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("priority", sa.String(16), nullable=False, comment="P1|P2|P3"),
        sa.Column("event", sa.String(32), nullable=False, comment="dispatch|unread|sla_warn|sla_breach|sla_breach_72h"),
        sa.Column("channels", postgresql.JSONB, nullable=False, comment="通道列表"),
        sa.Column("template", sa.Text, comment="消息模板"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="通知策略",
    )

    # audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.Integer, comment="操作人"),
        sa.Column("action", sa.String(64), nullable=False, comment="create|update|delete|dispatch|..."),
        sa.Column("target_type", sa.String(64), comment="work_order|config|..."),
        sa.Column("target_id", sa.Integer),
        sa.Column("detail", sa.Text, comment="JSON 详情"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="操作审计日志",
    )


def downgrade() -> None:
    for tbl in [
        "audit_log", "notification_policies", "approval_flows", "sla_definitions",
        "parsing_rules", "priority_rules", "workorder_type_kb", "person_project_map",
        "notification_log", "escalation_log", "attachments", "status_log",
        "work_orders", "config_definitions", "projects", "users",
    ]:
        op.drop_table(tbl)
