"""配置相关 Pydantic 模型"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ConfigDefinitionOut(BaseModel):
    id: int
    category: str
    code: str
    name: str
    color: str | None = None
    sort_order: int
    extra: dict | None = None
    model_config = {"from_attributes": True}


class PriorityRuleOut(BaseModel):
    id: int
    pattern: str
    label: str
    priority: str
    sort_order: int
    enabled: bool
    model_config = {"from_attributes": True}


class ParsingRuleOut(BaseModel):
    id: int
    name: str
    pattern: str
    weight: int
    sort_order: int
    enabled: bool
    model_config = {"from_attributes": True}


class PriorityRuleCreate(BaseModel):
    pattern: str
    label: str
    priority: str = "P2"


class PriorityRuleUpdate(BaseModel):
    pattern: str | None = None
    label: str | None = None
    priority: str | None = None
    enabled: bool | None = None


class SLADefinitionOut(BaseModel):
    id: int
    priority: str
    deadline_days: int
    warn_before_hours: int
    escalate_hours: float
    model_config = {"from_attributes": True}


class ApprovalFlowOut(BaseModel):
    id: int
    priority: str
    name: str
    nodes: list
    escalation: dict | None = None
    enabled: bool
    model_config = {"from_attributes": True}


class NotificationPolicyOut(BaseModel):
    id: int
    priority: str
    event: str
    channels: list
    template: str | None = None
    enabled: bool
    model_config = {"from_attributes": True}


class NotificationPolicyCreate(BaseModel):
    priority: str
    event: str
    channels: list[str]
    template: str | None = None


class WorkOrderTypeOut(BaseModel):
    id: int
    type_code: str
    name: str
    desc: str | None = None
    default_approver_id: int | None = None
    default_approver_role: str | None = None
    default_priority: str
    sort_order: int
    # SOP 字段
    guidance_ref: str | None = None
    sop_purpose: str | None = None
    sop_scope: str | None = None
    sop_steps: list | None = None
    sop_acceptance: str | None = None
    sop_backfill_required: bool = True
    sop_escalation: dict | None = None
    sop_related_guidance: list | None = None
    model_config = {"from_attributes": True}


class WorkOrderTypeCreate(BaseModel):
    type_code: str
    name: str
    desc: str | None = None
    default_approver_id: int | None = None
    default_approver_role: str | None = None
    default_priority: str = "P2"
    # SOP 字段
    guidance_ref: str | None = None
    sop_purpose: str | None = None
    sop_scope: str | None = None
    sop_steps: list | None = None
    sop_acceptance: str | None = None
    sop_backfill_required: bool = True
    sop_escalation: dict | None = None
    sop_related_guidance: list | None = None


class WorkOrderTypeUpdate(BaseModel):
    """工单类型更新：所有字段可选，仅更新传入的字段"""
    type_code: str | None = None
    name: str | None = None
    desc: str | None = None
    default_approver_id: int | None = None
    default_approver_role: str | None = None
    default_priority: str | None = None
    guidance_ref: str | None = None
    sop_purpose: str | None = None
    sop_scope: str | None = None
    sop_steps: list | None = None
    sop_acceptance: str | None = None
    sop_backfill_required: bool | None = None
    sop_escalation: dict | None = None
    sop_related_guidance: list | None = None


class PersonMapOut(BaseModel):
    id: int
    project_id: int
    user_id: int
    is_default: bool
    project_name: str | None = None
    user_name: str | None = None
    model_config = {"from_attributes": True}


class PersonMapCreate(BaseModel):
    project_id: int
    user_id: int
    is_default: bool = False


class ConfigDefCreate(BaseModel):
    category: str
    code: str
    name: str
    color: str | None = None


class ProjectOut(BaseModel):
    id: int
    code: str
    name: str
    type: str | None = None
    region: str | None = None
    dingtalk_group_id: str | None = None
    entry_date: str | None = None
    product_series: str | None = None
    judgment_date: str | None = None
    judgment_event_id: str | None = None
    judgment_status: str | None = None
    judgment_error: str | None = None
    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    name: str
    role: str
    department: str | None = None
    model_config = {"from_attributes": True}


class RegionPMOOut(BaseModel):
    id: int
    region: str
    user_id: int
    user_name: str | None = None
    model_config = {"from_attributes": True}


class RegionPMOCreate(BaseModel):
    region: str
    user_id: int


class RoleAssignmentOut(BaseModel):
    id: int
    role_code: str
    role_name: str
    user_id: int | None = None
    user_name: str | None = None
    sort_order: int
    model_config = {"from_attributes": True}


class RoleAssignmentUpdate(BaseModel):
    user_id: int | None = None
