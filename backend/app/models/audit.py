"""审计日志"""
from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """操作审计日志（仅 created_at，不记录 updated_at）"""
    __tablename__ = "audit_log"
    __table_args__ = {"comment": "操作审计日志"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(comment="操作人")
    action: Mapped[str] = mapped_column(comment="create|update|delete|dispatch|...")
    target_type: Mapped[str | None] = mapped_column(comment="work_order|config|...")
    target_id: Mapped[int | None] = mapped_column()
    detail: Mapped[str | None] = mapped_column(Text, comment="JSON 详情")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
