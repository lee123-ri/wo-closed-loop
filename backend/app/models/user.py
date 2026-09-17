"""用户模型"""
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = {"comment": "用户（责任人/审批人/管理员）"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    dingtalk_id: Mapped[str | None] = mapped_column(String(128), comment="钉钉 unionId/userId")
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))
    department: Mapped[str | None] = mapped_column(String(128), comment="部门名称")
    department_id: Mapped[str | None] = mapped_column(String(32), comment="钉钉部门ID")
    role: Mapped[str] = mapped_column(String(32), default="executor", comment="admin|approver|executor|readonly")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(256), comment="本地登录密码（钉钉登录可空）")
