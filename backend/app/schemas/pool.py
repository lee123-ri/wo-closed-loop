"""数据池相关 Pydantic 模型"""
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class PoolItemCreate(BaseModel):
    """单条数据池记录写入"""
    pool_type: str = Field(..., description="plan|anomaly")
    source_system: str = "manual"
    source_ref: str | None = None
    title: str = Field(..., max_length=512)
    project_name: str | None = None
    person_name: str | None = None
    deadline: date | None = None
    description: str | None = None
    metric_type: str | None = None
    metric_value: float | None = None
    threshold: float | None = None
    deviation_pct: float | None = None
    raw_data: dict[str, Any] | None = None


class PoolItemUpdate(BaseModel):
    """编辑数据池记录（生成前修正）"""
    title: str | None = None
    project_name: str | None = None
    person_name: str | None = None
    deadline: date | None = None
    description: str | None = None
    metric_type: str | None = None
    metric_value: float | None = None
    threshold: float | None = None
    deviation_pct: float | None = None
    status: str | None = None
    skip_reason: str | None = None


class PoolItemOut(BaseModel):
    id: int
    pool_type: str
    source_system: str
    source_ref: str | None = None
    title: str
    project_name: str | None = None
    person_name: str | None = None
    deadline: date | None = None
    description: str | None = None
    metric_type: str | None = None
    metric_value: float | None = None
    threshold: float | None = None
    deviation_pct: float | None = None
    status: str
    work_order_id: int | None = None
    skip_reason: str | None = None
    raw_data: dict[str, Any] | None = None
    backfill_reason: str | None = None
    backfill_action: str | None = None
    backfilled_at: datetime | None = None
    created_at: datetime

    # 关联名称
    work_order_code: str | None = None

    model_config = {"from_attributes": True}


class PoolItemListOut(BaseModel):
    items: list[PoolItemOut]
    total: int
    page: int
    page_size: int


class GenerateRequest(BaseModel):
    pool_ids: list[int] = Field(..., min_length=1, max_length=500)


class GenerateResult(BaseModel):
    generated: int
    skipped: int
    errors: list[str]
    work_order_ids: list[int]


class PoolImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str]


class BackfillRequest(BaseModel):
    reason: str | None = None
    action: str | None = None
    trigger_new_wo: bool = False
    new_wo_title: str | None = None
    new_wo_deadline: date | None = None
    new_wo_person_name: str | None = None


class BackfillOut(BaseModel):
    work_order_id: int
    reason: str | None = None
    action: str | None = None
    triggered_wo_id: int | None = None
    backfilled_at: datetime