"""管理员可配置的权限、组织岗位、通知及运行事件中心。"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.core.database import get_db
from app.models import (BusinessRole, BusinessRoleAssignment, NotificationRule,
    OperationEvent, OrganizationMappingRule, OrganizationSyncCandidate,
    PermissionRole, Project, User, UserPermissionRole, WorkOrder)
from app.services.audit import log_audit
from app.services.operation_events import record_event
from app.services.organization import confirm_candidate, create_pending_candidate

router = APIRouter(prefix="/organization", tags=["organization"])
SCOPES = {"global", "region", "project"}

class BusinessRoleIn(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    name: str = Field(min_length=1, max_length=64)
    scope_type: str = "global"
    is_active: bool = True
class AssignmentIn(BaseModel):
    user_id: int; business_role_code: str; scope_type: str = "global"; scope_id: int | None = None; is_protected: bool = False
class CandidateIn(AssignmentIn):
    source_kind: str; source_value: str; confidence: int = Field(default=100, ge=0, le=100)
class MappingRuleIn(BaseModel):
    name: str; source_kind: str = Field(pattern="^(department|title|group)$"); pattern: str = Field(min_length=1, max_length=256)
    business_role_code: str; scope_type: str = "global"; enabled: bool = True
class PermissionRoleIn(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$"); name: str
    data_scopes: list[str] = Field(default_factory=list); menu_permissions: list[str] = Field(default_factory=list)
    action_permissions: list[str] = Field(default_factory=list); is_active: bool = True
class PermissionAssignmentIn(BaseModel):
    user_id: int; permission_role_id: int
class NotificationRuleIn(BaseModel):
    name: str; event: str; conditions: dict[str, Any] = Field(default_factory=dict); recipients: dict[str, Any] = Field(default_factory=dict)
    channels: list[str]; template: str | None = None; cooldown_minutes: int = Field(default=60, ge=0); enabled: bool = False

def _scope(kind: str, ident: int | None) -> None:
    if kind not in SCOPES: raise HTTPException(400, "作用范围只能是 global、region、project")
    if kind == "project" and not ident: raise HTTPException(400, "项目范围必须指定项目")
def _business_role(db: Session, code: str, active: bool = False) -> BusinessRole:
    query = db.query(BusinessRole).filter_by(code=code)
    if active: query = query.filter_by(is_active=True)
    row = query.first()
    if not row: raise HTTPException(400, "业务岗位不存在或已停用")
    return row
def _audit(db: Session, actor: User, action: str, target: str, ident: int, detail: dict) -> None:
    log_audit(db, actor_id=actor.id, action=action, target_type=target, target_id=ident, detail=detail)
def _permission_out(row: PermissionRole) -> dict:
    return {key: getattr(row, key) for key in ("id", "code", "name", "data_scopes", "menu_permissions", "action_permissions", "is_system", "is_active")}
def _business_out(row: BusinessRole) -> dict:
    return {key: getattr(row, key) for key in ("id", "code", "name", "scope_type", "is_active", "is_system")}
def _mapping_out(row: OrganizationMappingRule) -> dict:
    return {key: getattr(row, key) for key in ("id", "name", "source_kind", "pattern", "business_role_code", "scope_type", "enabled")}
def _notification_out(row: NotificationRule) -> dict:
    return {key: getattr(row, key) for key in ("id", "name", "event", "conditions", "recipients", "channels", "template", "cooldown_minutes", "enabled")}

def _channels(channels: list[str]) -> None:
    from app.services.notification_rules import ALLOWED_CHANNELS
    if not channels or set(channels) - ALLOWED_CHANNELS: raise HTTPException(400, "通知渠道仅允许 robot_private、robot_group")
@router.get("/notification-rules")
def list_notification_rules(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [_notification_out(row) for row in db.query(NotificationRule).order_by(NotificationRule.id)]
@router.post("/notification-rules", status_code=201)
def create_notification_rule(body: NotificationRuleIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _channels(body.channels); row = NotificationRule(**body.model_dump()); db.add(row); db.flush(); _audit(db, actor, "create_notification_rule", "notification_rule", row.id, {"name": row.name, "channels": row.channels, "enabled": row.enabled}); db.commit(); return _notification_out(row)
@router.patch("/notification-rules/{rule_id}")
def update_notification_rule(rule_id: int, body: NotificationRuleIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(NotificationRule, rule_id)
    if not row: raise HTTPException(404, "通知规则不存在")
    _channels(body.channels)
    for key, value in body.model_dump().items(): setattr(row, key, value)
    _audit(db, actor, "update_notification_rule", "notification_rule", row.id, {"enabled": row.enabled, "channels": row.channels}); db.commit(); return _notification_out(row)
@router.delete("/notification-rules/{rule_id}", status_code=204)
def delete_notification_rule(rule_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(NotificationRule, rule_id)
    if not row: raise HTTPException(404, "通知规则不存在")
    _audit(db, actor, "delete_notification_rule", "notification_rule", row.id, {}); db.delete(row); db.commit()
@router.post("/notification-rules/{rule_id}/preview")
def preview_notification(rule_id: int, work_order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rule, work_order = db.get(NotificationRule, rule_id), db.get(WorkOrder, work_order_id)
    if not rule or not work_order: raise HTTPException(404, "规则或工单不存在")
    from app.services.notification_rules import dispatch
    return dispatch(db, work_order, rule.event, dry_run=True, rule_ids={rule.id})
@router.get("/operation-events")
def list_operation_events(status: str | None = None, category: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    query = db.query(OperationEvent)
    if status: query = query.filter(OperationEvent.status == status)
    if category: query = query.filter(OperationEvent.category == category)
    total = query.count(); rows = query.order_by(OperationEvent.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{key: (getattr(row, key).isoformat() if key == "created_at" else getattr(row, key)) for key in ("id", "category", "status", "summary", "detail", "trace_id", "work_order_id", "notification_rule_id", "created_at")} for row in rows], "total": total, "page": page, "page_size": page_size}
