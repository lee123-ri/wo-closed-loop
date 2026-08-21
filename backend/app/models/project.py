"""项目模型"""
from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services.region_map import region_check_sql


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(region_check_sql(), name="ck_projects_region"),
        {"comment": "电站项目"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="项目编码")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="项目名称")
    type: Mapped[str | None] = mapped_column(String(32), comment="wind|pv|storage")
    region: Mapped[str | None] = mapped_column(String(64), comment="区域")
    dingtalk_group_id: Mapped[str | None] = mapped_column(String(128), comment="钉钉群 conversationId")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
