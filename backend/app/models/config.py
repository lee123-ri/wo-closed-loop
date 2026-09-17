"""配置类模型：所有可配置业务规则存数据库"""
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class ConfigDefinition(TimestampMixin, Base):
    """通用配置定义：来源、状态、工单类型等枚举型配置统一存此表"""
    __tablename__ = "config_definitions"
    __table_args__ = {"comment": "配置定义（来源/状态/工单类型等）"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), index=True, comment="source|status|workorder_type|priority")
    code: Mapped[str] = mapped_column(String(64), comment="编码")
    name: Mapped[str] = mapped_column(String(128), comment="显示名")
    color: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[dict | None] = mapped_column(JSONB, comment="扩展字段，如默认审批人/优先级/下一状态")


class PersonProjectMap(TimestampMixin, Base):
    """项目 → 可选责任人映射"""
    __tablename__ = "person_project_map"
    __table_args__ = {"comment": "人员-项目映射"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkOrderTypeKB(TimestampMixin, Base):
    """工单类型知识库（含结构化 SOP）"""
    __tablename__ = "workorder_type_kb"
    __table_args__ = {"comment": "工单类型知识库（含SOP）"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type_code: Mapped[str] = mapped_column(String(64), comment="类型编码")
    name: Mapped[str] = mapped_column(String(64))
    desc: Mapped[str | None] = mapped_column(Text)
    default_approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    default_approver_role: Mapped[str | None] = mapped_column(String(32), comment="默认审批人角色编码，如 division_head/pmo/delivery_pmo")
    default_priority: Mapped[str] = mapped_column(String(16), default="P2")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # SOP 结构化字段
    guidance_ref: Mapped[str | None] = mapped_column(String(128), comment="对应官方指引编号，如 YWSYB-GLZY-009")
    sop_purpose: Mapped[str | None] = mapped_column(Text, comment="SOP目的")
    sop_scope: Mapped[str | None] = mapped_column(Text, comment="适用范围")
    sop_steps: Mapped[list | None] = mapped_column(JSONB, comment="标准步骤 [{step,action,standard,role}]")
    sop_acceptance: Mapped[str | None] = mapped_column(Text, comment="验收标准")
    sop_backfill_required: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否要求回填原因措施")
    sop_escalation: Mapped[dict | None] = mapped_column(JSONB, comment="升级规则 {timeout_hours,action,target}")
    sop_related_guidance: Mapped[list | None] = mapped_column(JSONB, comment="关联指引 [{ref,title}]")


class PriorityRule(TimestampMixin, Base):
    """优先级判定规则（正则匹配，按顺序）"""
    __tablename__ = "priority_rules"
    __table_args__ = {"comment": "优先级判定规则"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(String(512), comment="正则表达式")
    label: Mapped[str] = mapped_column(String(128), comment="规则说明")
    priority: Mapped[str] = mapped_column(String(16), comment="P1|P2|P3")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ParsingRule(TimestampMixin, Base):
    """听记解析规则（评分）"""
    __tablename__ = "parsing_rules"
    __table_args__ = {"comment": "听记解析规则"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    pattern: Mapped[str] = mapped_column(String(512), comment="正则表达式")
    weight: Mapped[int] = mapped_column(Integer, default=1, comment="权重 1-5")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SLADefinition(TimestampMixin, Base):
    """SLA 定义（按优先级）"""
    __tablename__ = "sla_definitions"
    __table_args__ = {"comment": "SLA 定义"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    priority: Mapped[str] = mapped_column(String(16), unique=True, comment="P1|P2|P3")
    deadline_days: Mapped[int] = mapped_column(Integer, comment="截止天数")
    warn_before_hours: Mapped[int] = mapped_column(Integer, comment="到期前预警小时数")
    escalate_hours: Mapped[float] = mapped_column(Float, comment="违约后升级小时数")


class ApprovalFlow(TimestampMixin, Base):
    """审批流模板（按优先级路由）"""
    __tablename__ = "approval_flows"
    __table_args__ = {"comment": "审批流模板"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    priority: Mapped[str] = mapped_column(String(16), comment="P1|P2|P3")
    name: Mapped[str] = mapped_column(String(128))
    nodes: Mapped[list] = mapped_column(JSONB, comment="节点列表 [{type,title,sub,role,timeout_days}]")
    escalation: Mapped[dict | None] = mapped_column(JSONB, comment="{timeout_hours,action,target}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationPolicy(TimestampMixin, Base):
    """通知策略（优先级 × 事件类型）"""
    __tablename__ = "notification_policies"
    __table_args__ = {"comment": "通知策略"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    priority: Mapped[str] = mapped_column(String(16), comment="P1|P2|P3")
    event: Mapped[str] = mapped_column(String(32), comment="dispatch|unread|sla_warn|sla_breach|sla_breach_72h")
    channels: Mapped[list] = mapped_column(JSONB, comment="['phone_ding','work_notify','robot_mention']")
    template: Mapped[str | None] = mapped_column(Text, comment="消息模板")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class RegionPMO(TimestampMixin, Base):
    """区域 → PMO 映射"""
    __tablename__ = "region_pmos"
    __table_args__ = {"comment": "区域PMO映射"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, comment="华北/华中/华东/华南/西北/西南/东北")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


class RoleAssignment(TimestampMixin, Base):
    """组织角色 → 人员映射（审批流用角色编码引用，具体人名可后台配置）"""
    __tablename__ = "role_assignments"
    __table_args__ = {"comment": "组织角色-人员映射"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="division_head|pmo|delivery_pmo")
    role_name: Mapped[str] = mapped_column(String(64), comment="事业部负责人/事业部PMO/交付PMO")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
