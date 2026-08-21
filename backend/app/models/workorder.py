"""工单主表及关联子表"""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services.region_map import region_check_sql


class WorkOrder(TimestampMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(region_check_sql(), name="ck_work_orders_region"),
        {"comment": "工单主表"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="RW-2026-0001")
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, comment="触发原因")
    action: Mapped[str | None] = mapped_column(Text, comment="行动要求")
    conclusion: Mapped[str | None] = mapped_column(Text, comment="执行结论")

    # 关联
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    person_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), comment="责任人")
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), comment="审批人")
    type_id: Mapped[int | None] = mapped_column(ForeignKey("workorder_type_kb.id"), comment="工单类型")
    source_code: Mapped[str] = mapped_column(String(32), comment="来源 code")
    region: Mapped[str | None] = mapped_column(String(16), comment="区域：华北/华中/华东/华南/西北/西南/东北")
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="状态 code")
    priority: Mapped[str] = mapped_column(String(32), default="P2", comment="P1|P2|P3")

    # 日期
    created_date: Mapped[date] = mapped_column(Date, comment="工单创建日（业务日）")
    planned_start_date: Mapped[date | None] = mapped_column(Date, comment="计划开始时间")
    deadline: Mapped[date | None] = mapped_column(Date)
    completed_date: Mapped[date | None] = mapped_column(Date)

    # 钉钉
    oa_id: Mapped[str | None] = mapped_column(String(64), comment="钉钉 OA 审批单号")
    oa_progress: Mapped[list | None] = mapped_column(JSONB, comment="OA审批进度 [{stage,role,title,user_id,dingtalk_id,approved}]")

    # SLA
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, comment="0|1|2|3")
    overdue_days: Mapped[int] = mapped_column(Integer, default=0)

    # 回填（Phase 3.5）
    backfill_status: Mapped[str | None] = mapped_column(String(16), comment="pending|filled")
    backfill_reason: Mapped[str | None] = mapped_column(Text, comment="责任人填写的根因分析")
    backfill_action: Mapped[str | None] = mapped_column(Text, comment="责任人填写的应对措施")
    backfilled_at: Mapped[datetime | None] = mapped_column(DateTime, comment="回填时间")

    # 溯源（Phase 3.5）
    parent_pool_id: Mapped[int | None] = mapped_column(ForeignKey("data_pool_items.id"), comment="来源数据池记录")
    triggered_wo_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), comment="回填后触发的新工单")

    # 回填增强：PMO建议的新工单参数
    triggered_wo_title: Mapped[str | None] = mapped_column(String(256), comment="PMO建议的新工单标题")
    triggered_wo_deadline: Mapped[date | None] = mapped_column(Date, comment="PMO建议的截止时间")
    triggered_wo_tasks: Mapped[list | None] = mapped_column(JSONB, comment="措施工单任务列表 [{title, person_name, deadline}]")
    triggered_wo_person_name: Mapped[str | None] = mapped_column(String(64), comment="PMO建议的责任人")

    # 判断Agent（Phase 5）
    judgment_status: Mapped[str | None] = mapped_column(String(32), comment="None|pending_judge|judging|approved|rejected|no_action_needed|degraded")
    judgment_result: Mapped[dict | None] = mapped_column(JSONB, comment="Agent返回的完整判定结果")
    judgment_requested_at: Mapped[datetime | None] = mapped_column(DateTime, comment="提交判断时间")
    judgment_completed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="判断完成时间")


class AgentImportBatch(TimestampMixin, Base):
    """可靠性Agent导入批次：记录「项目×异常指标×周期」已导入，防止重复建单。

    一次分析（如 泰康师宗 FLE50 4~5月）→ 一批工单（9张）。同批次重导直接跳过整批。
    """

    __tablename__ = "agent_import_batches"
    __table_args__ = {"comment": "可靠性Agent导入批次（按项目+指标+周期去重）"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, comment="项目|指标|周期")
    project_name: Mapped[str | None] = mapped_column(String(128), comment="项目简称")
    metric_type: Mapped[str | None] = mapped_column(String(32), comment="异常指标，如 FLE50")
    period: Mapped[str | None] = mapped_column(String(64), comment="分析周期，如 2026-04~05")
    source_system: Mapped[str | None] = mapped_column(String(32), default="指标异常处置SOP", comment="产出Agent")
    work_order_codes: Mapped[list | None] = mapped_column(JSONB, comment="本批次生成的工单编号列表")


class StatusLog(TimestampMixin, Base):
    __tablename__ = "status_log"
    __table_args__ = {"comment": "工单状态流转日志"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = {"comment": "工单佐证附件"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(256))
    oss_key: Mapped[str] = mapped_column(String(512), comment="OSS 对象 key")
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class EscalationLog(TimestampMixin, Base):
    __tablename__ = "escalation_log"
    __table_args__ = {"comment": "升级记录"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer, comment="升级到第几级")
    triggered_at: Mapped[datetime] = mapped_column(comment="触发时间")
    target: Mapped[str | None] = mapped_column(String(128), comment="升级目标人")


class NotificationLog(TimestampMixin, Base):
    __tablename__ = "notification_log"
    __table_args__ = {"comment": "通知发送记录"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(32), comment="ding|robot|sms|phone")
    recipient: Mapped[str] = mapped_column(String(128))
    event: Mapped[str] = mapped_column(String(64), comment="dispatch|unread|sla_warn|sla_breach|sla_breach_72h")
    status: Mapped[str] = mapped_column(String(16), default="sent", comment="sent|failed")
    message: Mapped[str | None] = mapped_column(Text)
