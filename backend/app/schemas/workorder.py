"""工单相关 Pydantic 模型"""
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkOrderBase(BaseModel):
    title: str = Field(..., max_length=256)
    reason: str | None = None
    action: str | None = None
    project_id: int | None = None
    person_id: int | None = None
    approver_id: int | None = None
    type_id: int | None = None
    source_code: str
    priority: str = "P2"
    deadline: date | None = None


class WorkOrderCreate(WorkOrderBase):
    parent_pool_id: int | None = None  # 来源数据池记录


class WorkOrderUpdate(BaseModel):
    title: str | None = None
    reason: str | None = None
    action: str | None = None
    status: str | None = None
    person_id: int | None = None
    approver_id: int | None = None
    priority: str | None = None
    deadline: date | None = None
    completed_date: date | None = None
    conclusion: str | None = None
    # 回填
    backfill_status: str | None = None
    backfill_reason: str | None = None
    backfill_action: str | None = None


class WorkOrderOut(WorkOrderBase):
    id: int
    code: str
    status: str
    type_id: int | None
    created_date: date
    deadline: date | None
    completed_date: date | None
    oa_id: str | None
    escalation_level: int
    overdue_days: int
    conclusion: str | None
    created_at: datetime
    # 关联名称（join 查询填充）
    project_name: str | None = None
    person_name: str | None = None
    approver_name: str | None = None
    type_name: str | None = None
    # 闭环归档用
    duration_days: int | None = None
    is_overdue: bool = False
    # 回填（Phase 3.5）
    backfill_status: str | None = None
    backfill_reason: str | None = None
    backfill_action: str | None = None
    backfilled_at: datetime | None = None
    parent_pool_id: int | None = None
    triggered_wo_id: int | None = None
    # 触发的新工单编号
    triggered_wo_code: str | None = None

    model_config = {"from_attributes": True}


class WorkOrderListOut(BaseModel):
    items: list[WorkOrderOut]
    total: int
    page: int
    page_size: int


class StatusLogOut(BaseModel):
    id: int
    from_status: str | None
    to_status: str
    operator_name: str | None = None
    note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClosedItemOut(WorkOrderOut):
    duration_days: int | None = None
    is_overdue: bool = False


class DashboardStats(BaseModel):
    total: int
    executing: int
    pending_verify: int
    overdue: int
    closed: int
    sla_compliance: float
    mttr_days: float | None
    mtta_days: float | None
    closed_rate: float
    aging: dict[str, int]
    source_dist: list[dict[str, Any]]
    overdue_items: list[dict[str, Any]]
    todo_items: list[dict[str, Any]]
