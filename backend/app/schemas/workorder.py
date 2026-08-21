"""工单相关 Pydantic 模型"""
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.region_map import normalize_region


class WorkOrderBase(BaseModel):
    title: str = Field(..., max_length=256)
    reason: str | None = None
    action: str | None = None
    project_id: int | None = None
    person_id: int | None = None
    approver_id: int | None = None
    type_id: int | None = None
    source_code: str
    region: str | None = Field(None, description="区域：华北/华中/华东/华南/西北/西南/东北")
    priority: str | None = None  # None=未指定，建单时按文本自动定级
    planned_start_date: date | None = None
    deadline: date | None = None

    @field_validator("region")
    @classmethod
    def _norm_region(cls, v: str | None) -> str | None:
        # 限缩到七大区：省份/组织名自动归一化，识别不了的空掉
        return normalize_region(v)


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
    region: str | None = None
    planned_start_date: date | None = None
    deadline: date | None = None
    completed_date: date | None = None
    conclusion: str | None = None

    @field_validator("region")
    @classmethod
    def _norm_region(cls, v: str | None) -> str | None:
        return normalize_region(v)
    # 回填
    backfill_status: str | None = None
    backfill_reason: str | None = None
    backfill_action: str | None = None
    # 措施工单草稿任务列表（判断界面可编辑保存，[{title, reason, action, person_name, deadline, type_id, priority}]）
    triggered_wo_tasks: list | None = None


class CloseNoDispatchRequest(BaseModel):
    """不发现场关闭：必填关闭原因，可选操作人"""
    reason: str = Field(..., min_length=1, max_length=2000, description="关闭原因（必填，写入AITable台账）")
    operator_name: str | None = Field(None, max_length=64, description="操作人姓名，缺省时为空")


class WorkOrderOut(WorkOrderBase):
    id: int
    code: str
    status: str
    type_id: int | None
    created_date: date
    planned_start_date: date | None
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
    region: str | None = None  # 工单运营区域
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
    # 措施工单草稿任务列表（判断界面）
    triggered_wo_tasks: list | None = None
    # 判断Agent（Phase 5）
    judgment_status: str | None = None
    judgment_result: dict[str, Any] | None = None
    judgment_requested_at: datetime | None = None
    judgment_completed_at: datetime | None = None
    # 不发现场关闭（2026-08）
    closed_without_dispatch: bool | None = None
    no_dispatch_reason: str | None = None
    no_dispatch_synced: bool | None = None

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
