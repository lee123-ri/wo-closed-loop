"""判断Agent 降级日志模型"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JudgmentDegradationLog(Base):
    __tablename__ = "judgment_degradation_log"
    __table_args__ = {"comment": "判断Agent降级记录"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="关联工单")
    reason: Mapped[str] = mapped_column(String(64), nullable=False, comment="timeout|unreachable|parse_error|server_error")
    original_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())