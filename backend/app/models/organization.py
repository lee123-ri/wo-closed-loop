"""组织事实同步与确认后的岗位关系。"""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.base import TimestampMixin

class PermissionRole(TimestampMixin, Base):
    __tablename__ = "permission_roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    data_scopes: Mapped[list] = mapped_column(JSONB, default=list)
    menu_permissions: Mapped[list] = mapped_column(JSONB, default=list)
    action_permissions: Mapped[list] = mapped_column(JSONB, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class UserPermissionRole(TimestampMixin, Base):
    __tablename__ = "user_permission_roles"
    __table_args__ = (UniqueConstraint("user_id", "permission_role_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    permission_role_id: Mapped[int] = mapped_column(ForeignKey("permission_roles.id", ondelete="CASCADE"), index=True)

class BusinessRole(TimestampMixin, Base):
    __tablename__ = "business_roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    scope_type: Mapped[str] = mapped_column(String(16), default="global")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

class BusinessRoleAssignment(TimestampMixin, Base):
    __tablename__ = "business_role_assignments"
    __table_args__ = (UniqueConstraint("user_id", "business_role_id", "scope_type", "scope_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    business_role_id: Mapped[int] = mapped_column(ForeignKey("business_roles.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(16), default="global")
    scope_id: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False)

class OrganizationSyncCandidate(TimestampMixin, Base):
    __tablename__ = "organization_sync_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    business_role_code: Mapped[str] = mapped_column(String(64))
    scope_type: Mapped[str] = mapped_column(String(16), default="global")
    scope_id: Mapped[int | None] = mapped_column(Integer)
    source_kind: Mapped[str] = mapped_column(String(32))
    source_value: Mapped[str] = mapped_column(Text)
    confidence: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(16), default="pending")


class OrganizationMappingRule(TimestampMixin, Base):
    """管理员维护的钉钉字段到标准业务岗位的映射规则。"""
    __tablename__ = "organization_mapping_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # department|title|group
    pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    business_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), default="global")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationRule(TimestampMixin, Base):
    """仅允许机器人私聊/群聊的可配置通知规则。"""
    __tablename__ = "notification_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    conditions: Mapped[dict | None] = mapped_column(JSONB)
    recipients: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    channels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    template: Mapped[str | None] = mapped_column(Text)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class OperationEvent(TimestampMixin, Base):
    """运维可检索的关键运行事件；完整 traceback 保留文件日志。"""
    __tablename__ = "operation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # notification|sync|escalation|oa
    status: Mapped[str] = mapped_column(String(16), nullable=False)    # started|success|failed|skipped
    summary: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id", ondelete="SET NULL"), index=True)
    notification_rule_id: Mapped[int | None] = mapped_column(ForeignKey("notification_rules.id", ondelete="SET NULL"), index=True)
