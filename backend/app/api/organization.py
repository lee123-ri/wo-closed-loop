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

@router.get("/permission-roles")
def list_permission_roles(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [_permission_out(row) for row in db.query(PermissionRole).order_by(PermissionRole.name)]
@router.post("/permission-roles", status_code=201)
def create_permission_role(body: PermissionRoleIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if db.query(PermissionRole).filter_by(code=body.code).first(): raise HTTPException(409, "权限角色编码已存在")
    row = PermissionRole(**body.model_dump()); db.add(row); db.flush(); _audit(db, actor, "create_permission_role", "permission_role", row.id, {"code": row.code}); db.commit(); return _permission_out(row)
@router.patch("/permission-roles/{role_id}")
def update_permission_role(role_id: int, body: PermissionRoleIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(PermissionRole, role_id)
    if not row: raise HTTPException(404, "权限角色不存在")
    if row.is_system and body.code != row.code: raise HTTPException(400, "系统权限角色编码不可修改")
    if db.query(PermissionRole).filter(PermissionRole.code == body.code, PermissionRole.id != role_id).first(): raise HTTPException(409, "权限角色编码已存在")
    for key, value in body.model_dump().items(): setattr(row, key, value)
    _audit(db, actor, "update_permission_role", "permission_role", row.id, {"code": row.code}); db.commit(); return _permission_out(row)
@router.post("/permission-assignments", status_code=201)
def assign_permission_role(body: PermissionAssignmentIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not db.get(User, body.user_id): raise HTTPException(404, "人员不存在")
    role = db.get(PermissionRole, body.permission_role_id)
    if not role or not role.is_active: raise HTTPException(400, "权限角色不存在或已停用")
    row = db.query(UserPermissionRole).filter_by(**body.model_dump()).first()
    if row: return {"id": row.id, "created": False}
    row = UserPermissionRole(**body.model_dump()); db.add(row); db.flush(); _audit(db, actor, "assign_permission_role", "user", body.user_id, {"permission_role": role.code}); db.commit(); return {"id": row.id, "created": True}
@router.delete("/permission-assignments/{assignment_id}", status_code=204)
def revoke_permission_role(assignment_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(UserPermissionRole, assignment_id)
    if not row: raise HTTPException(404, "权限角色分配不存在")
    _audit(db, actor, "revoke_permission_role", "user", row.user_id, {"permission_role_id": row.permission_role_id}); db.delete(row); db.commit()

@router.get("/business-roles")
def list_business_roles(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [_business_out(row) for row in db.query(BusinessRole).order_by(BusinessRole.name)]
@router.post("/business-roles", status_code=201)
def create_business_role(body: BusinessRoleIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _scope(body.scope_type, None)
    if db.query(BusinessRole).filter_by(code=body.code).first(): raise HTTPException(409, "岗位编码已存在")
    row = BusinessRole(**body.model_dump()); db.add(row); db.flush(); _audit(db, actor, "create_business_role", "business_role", row.id, {"code": row.code}); db.commit(); return _business_out(row)
@router.patch("/business-roles/{role_id}")
def update_business_role(role_id: int, body: BusinessRoleIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(BusinessRole, role_id)
    if not row: raise HTTPException(404, "业务岗位不存在")
    if row.is_system and body.code != row.code: raise HTTPException(400, "系统业务岗位编码不可修改")
    _scope(body.scope_type, None)
    if db.query(BusinessRole).filter(BusinessRole.code == body.code, BusinessRole.id != role_id).first(): raise HTTPException(409, "岗位编码已存在")
    for key, value in body.model_dump().items(): setattr(row, key, value)
    _audit(db, actor, "update_business_role", "business_role", row.id, {"code": row.code, "active": row.is_active}); db.commit(); return _business_out(row)
@router.get("/business-assignments")
def list_business_assignments(user_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    query = db.query(BusinessRoleAssignment, BusinessRole, User).join(BusinessRole).join(User)
    if user_id: query = query.filter(BusinessRoleAssignment.user_id == user_id)
    return [{"id": a.id, "user_id": u.id, "user_name": u.name, "business_role_code": r.code, "business_role_name": r.name, "scope_type": a.scope_type, "scope_id": a.scope_id, "source": a.source, "is_confirmed": a.is_confirmed, "is_protected": a.is_protected} for a, r, u in query.order_by(BusinessRoleAssignment.id.desc())]
@router.post("/business-assignments", status_code=201)
def create_business_assignment(body: AssignmentIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not db.get(User, body.user_id): raise HTTPException(404, "人员不存在")
    _scope(body.scope_type, body.scope_id); role = _business_role(db, body.business_role_code, active=True)
    row = db.query(BusinessRoleAssignment).filter_by(user_id=body.user_id, business_role_id=role.id, scope_type=body.scope_type, scope_id=body.scope_id).first()
    if row: return {"id": row.id, "created": False}
    row = BusinessRoleAssignment(user_id=body.user_id, business_role_id=role.id, scope_type=body.scope_type, scope_id=body.scope_id, source="manual", is_confirmed=True, is_protected=body.is_protected)
    db.add(row); db.flush(); _audit(db, actor, "create_business_assignment", "business_role_assignment", row.id, body.model_dump()); db.commit(); return {"id": row.id, "created": True}
@router.delete("/business-assignments/{assignment_id}", status_code=204)
def delete_business_assignment(assignment_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(BusinessRoleAssignment, assignment_id)
    if not row: raise HTTPException(404, "岗位分配不存在")
    _audit(db, actor, "delete_business_assignment", "business_role_assignment", row.id, {"protected": row.is_protected}); db.delete(row); db.commit()

@router.get("/sync-candidates")
def list_candidates(status: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    query = db.query(OrganizationSyncCandidate)
    if status: query = query.filter_by(status=status)
    return [{key: getattr(row, key) for key in ("id", "user_id", "business_role_code", "scope_type", "scope_id", "source_kind", "source_value", "confidence", "status")} for row in query.order_by(OrganizationSyncCandidate.id.desc())]
@router.post("/sync-candidates", status_code=201)
def create_candidate(body: CandidateIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not db.get(User, body.user_id): raise HTTPException(404, "人员不存在")
    _scope(body.scope_type, body.scope_id); _business_role(db, body.business_role_code, active=True)
    data = body.model_dump(exclude={"is_protected"})
    row, created = create_pending_candidate(db, data)
    if created: _audit(db, actor, "create_org_sync_candidate", "organization_sync_candidate", row.id, data)
    db.commit(); return {"id": row.id, "status": row.status, "created": created}
@router.post("/sync-candidates/{candidate_id}/confirm")
def confirm_sync_candidate(candidate_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(OrganizationSyncCandidate, candidate_id)
    if not row or row.status != "pending": raise HTTPException(404, "待确认岗位不存在或已处理")
    try: assignment = confirm_candidate(db, row)
    except ValueError as error: raise HTTPException(400, str(error)) from error
    _audit(db, actor, "confirm_org_sync_candidate", "organization_sync_candidate", row.id, {"assignment_id": assignment.id}); record_event(db, category="sync", status="success", summary="组织岗位候选已确认", detail={"candidate_id": row.id, "assignment_id": assignment.id}); db.commit(); return {"id": row.id, "status": row.status, "assignment_id": assignment.id}
@router.post("/sync-candidates/{candidate_id}/reject")
def reject_sync_candidate(candidate_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(OrganizationSyncCandidate, candidate_id)
    if not row or row.status != "pending": raise HTTPException(404, "待确认岗位不存在或已处理")
    row.status = "rejected"; _audit(db, actor, "reject_org_sync_candidate", "organization_sync_candidate", row.id, {}); db.commit(); return {"id": row.id, "status": row.status}

@router.get("/mapping-rules")
def list_mapping_rules(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [_mapping_out(row) for row in db.query(OrganizationMappingRule).order_by(OrganizationMappingRule.id)]
@router.post("/mapping-rules", status_code=201)
def create_mapping_rule(body: MappingRuleIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    _scope(body.scope_type, None); _business_role(db, body.business_role_code)
    row = OrganizationMappingRule(**body.model_dump()); db.add(row); db.flush(); _audit(db, actor, "create_org_mapping_rule", "organization_mapping_rule", row.id, body.model_dump()); db.commit(); return _mapping_out(row)
@router.patch("/mapping-rules/{rule_id}")
def update_mapping_rule(rule_id: int, body: MappingRuleIn, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(OrganizationMappingRule, rule_id)
    if not row: raise HTTPException(404, "映射规则不存在")
    _scope(body.scope_type, None); _business_role(db, body.business_role_code)
    for key, value in body.model_dump().items(): setattr(row, key, value)
    _audit(db, actor, "update_org_mapping_rule", "organization_mapping_rule", row.id, body.model_dump()); db.commit(); return _mapping_out(row)
@router.delete("/mapping-rules/{rule_id}", status_code=204)
def delete_mapping_rule(rule_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row = db.get(OrganizationMappingRule, rule_id)
    if not row: raise HTTPException(404, "映射规则不存在")
    _audit(db, actor, "delete_org_mapping_rule", "organization_mapping_rule", row.id, {}); db.delete(row); db.commit()

def _group_members(project: Project) -> list[dict]:
    if not project.dingtalk_group_id: raise HTTPException(400, "项目未关联钉钉群")
    from app.services.dingtalk import get_group_members
    return get_group_members(project.dingtalk_group_id)
def _member_ids(members: list[dict]) -> set[str]:
    return {str(member.get("dingtalk_id") or member.get("userid") or member.get("userId") or member.get("user_id") or "") for member in members} - {""}
@router.post("/projects/{project_id}/sync-preview")
def project_group_preview(project_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    project = db.get(Project, project_id)
    if not project: raise HTTPException(404, "项目不存在")
    ids = _member_ids(_group_members(project)); known = {user.dingtalk_id: user for user in db.query(User).filter(User.dingtalk_id.in_(ids)).all() if user.dingtalk_id}
    return {"project_id": project.id, "group_id": project.dingtalk_group_id, "suggested_role": "site_member", "members": [{"dingtalk_id": ident, "known_user_id": known[ident].id if ident in known else None} for ident in ids], "note": "预览不写入；仅已绑定钉钉 ID 的人员可生成待确认候选"}
@router.post("/projects/{project_id}/sync-candidates")
def project_group_candidates(project_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    project = db.get(Project, project_id)
    if not project: raise HTTPException(404, "项目不存在")
    ids = _member_ids(_group_members(project)); users = {user.dingtalk_id: user for user in db.query(User).filter(User.dingtalk_id.in_(ids)).all() if user.dingtalk_id}; created = 0
    for user in users.values():
        _, did_create = create_pending_candidate(db, {"user_id": user.id, "business_role_code": "site_member", "scope_type": "project", "scope_id": project.id, "source_kind": "group", "source_value": project.dingtalk_group_id, "confidence": 100}); created += int(did_create)
    record_event(db, category="sync", status="success", summary="项目群成员已生成岗位候选", detail={"project_id": project.id, "members": len(ids), "matched": len(users), "created": created}); _audit(db, actor, "create_project_group_candidates", "project", project.id, {"matched": len(users), "created": created}); db.commit(); return {"created": created, "matched": len(users), "unmatched": len(ids) - len(users), "status": "pending_confirmation"}

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
