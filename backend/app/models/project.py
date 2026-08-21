"""项目模型"""
from datetime import date

from sqlalchemy import CheckConstraint, Date, String
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

    # ── 试运营判定会（新入场自动建会）────────────────────
    entry_date: Mapped[date | None] = mapped_column(Date, comment="入场日期")
    product_series: Mapped[str | None] = mapped_column(String(32), comment="产品系列 HS100/HS200/HS300/HS400/HS500/500Pro")
    judgment_date: Mapped[date | None] = mapped_column(Date, comment="判定日 = 入场日期 + 判定天数 - 1")
    judgment_event_id: Mapped[str | None] = mapped_column(String(128), comment="钉钉日历日程 eventId（幂等）")
    judgment_status: Mapped[str | None] = mapped_column(String(32), comment="pending|created|failed")
    judgment_error: Mapped[str | None] = mapped_column(String(512), comment="建会失败原因")
