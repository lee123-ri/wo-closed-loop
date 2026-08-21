"""数据池模型：统一暂存计划类+异常指标类待办，作为工单生成的数据源"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class DataPoolItem(TimestampMixin, Base):
    """统一数据池：计划类(plan) + 异常指标类(anomaly)"""

    __tablename__ = "data_pool_items"
    __table_args__ = {"comment": "数据池-暂存待生成工单的原始数据"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pool_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="plan|anomaly")
    source_system: Mapped[str] = mapped_column(String(32), default="manual", comment="excel|aitable|asset_monitor|manual")
    source_ref: Mapped[str | None] = mapped_column(String(256), comment="来源文件名/表名/AI表格 recordId")

    # 核心字段
    title: Mapped[str] = mapped_column(String(512), nullable=False, comment="事项标题")
    project_name: Mapped[str | None] = mapped_column(String(128), comment="场站名（映射前原始值）")
    person_name: Mapped[str | None] = mapped_column(String(64), comment="责任人（映射前原始值）")
    priority: Mapped[str | None] = mapped_column(String(16), comment="计划类自带优先级 P1|P2|P3；异常指标固定P1")
    deadline: Mapped[date | None] = mapped_column(Date, comment="截止日期")
    description: Mapped[str | None] = mapped_column(Text, comment="描述/触发原因")

    # 异常指标专用
    metric_type: Mapped[str | None] = mapped_column(String(32), comment="power_gen|curtailment|reliability|dual_rule")
    metric_value: Mapped[float | None] = mapped_column(Float, comment="指标值")
    threshold: Mapped[float | None] = mapped_column(Float, comment="阈值")
    deviation_pct: Mapped[float | None] = mapped_column(Float, comment="偏离百分比")

    # 处理状态
    status: Mapped[str] = mapped_column(String(16), default="pending", comment="pending|generated|skipped")
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), comment="生成后关联工单")
    skip_reason: Mapped[str | None] = mapped_column(String(256), comment="跳过原因")

    # 原始数据（JSONB 保留完整来源行，含所有额外列）
    raw_data: Mapped[dict | None] = mapped_column(JSONB, comment="原始数据行（JSON）")

    # 回填回来的数据（从工单回传）
    backfill_reason: Mapped[str | None] = mapped_column(Text, comment="回填-根因分析")
    backfill_action: Mapped[str | None] = mapped_column(Text, comment="回填-应对措施")
    backfilled_at: Mapped[datetime | None] = mapped_column(DateTime, comment="回填时间")