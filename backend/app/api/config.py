"""配置管理 API：来源/状态/类型/优先级规则/SLA/审批流/项目/人员"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.auth import require_auth
from app.models import (
    ApprovalFlow, ConfigDefinition, NotificationPolicy, ParsingRule, PriorityRule, Project, SLADefinition,
    User, WorkOrderTypeKB, PersonProjectMap, RegionPMO, RoleAssignment,
)
from app.schemas.config import (
    ApprovalFlowOut, ConfigDefCreate, ConfigDefinitionOut, NotificationPolicyCreate,
    NotificationPolicyOut, ParsingRuleOut, PersonMapCreate, PersonMapOut,
    PriorityRuleCreate, PriorityRuleOut, PriorityRuleUpdate, ProjectOut, SLADefinitionOut, UserOut,
    WorkOrderTypeCreate, WorkOrderTypeOut, WorkOrderTypeUpdate,
    RegionPMOOut, RegionPMOCreate, RoleAssignmentOut, RoleAssignmentUpdate,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/sources", response_model=list[ConfigDefinitionOut])
def list_sources(db: Session = Depends(get_db)):
    return db.query(ConfigDefinition).filter_by(category="source").order_by(ConfigDefinition.sort_order).all()


@router.get("/statuses", response_model=list[ConfigDefinitionOut])
def list_statuses(db: Session = Depends(get_db)):
    return db.query(ConfigDefinition).filter_by(category="status").order_by(ConfigDefinition.sort_order).all()


@router.get("/work-order-types", response_model=list[ConfigDefinitionOut])
def list_wo_types(db: Session = Depends(get_db)):
    """工单类型（从 workorder_type_kb 取）"""
    rows = db.query(WorkOrderTypeKB).order_by(WorkOrderTypeKB.sort_order).all()
    return [
        ConfigDefinitionOut(
            id=r.id, category="workorder_type", code=r.type_code, name=r.name,
            color=None, sort_order=r.sort_order,
            extra={"desc": r.desc, "default_priority": r.default_priority},
        )
        for r in rows
    ]


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), page: int = 1, page_size: int = 50):
    return db.query(Project).filter(Project.is_active.is_(True)).order_by(Project.id).offset((page-1)*page_size).limit(page_size).all()

@router.get("/projects/all", response_model=list[ProjectOut])
def list_all_projects(db: Session = Depends(get_db)):
    """不分页，给下拉选择器用"""
    return db.query(Project).filter(Project.is_active.is_(True)).order_by(Project.name).all()


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), page: int = 1, page_size: int = 50, _: User = Depends(require_auth)):
    return db.query(User).filter(User.is_active.is_(True)).order_by(User.id).offset((page-1)*page_size).limit(page_size).all()

@router.get("/users/all", response_model=list[UserOut])
def list_all_users(db: Session = Depends(get_db), _: User = Depends(require_auth)):
    """不分页，给下拉选择器用"""
    return db.query(User).filter(User.is_active.is_(True)).order_by(User.name).all()


@router.get("/person-project-map")
def person_project_map(db: Session = Depends(get_db)):
    """项目 → 责任人列表"""
    rows = db.query(PersonProjectMap, Project, User).join(
        Project, PersonProjectMap.project_id == Project.id
    ).join(User, PersonProjectMap.user_id == User.id).all()
    result: dict[int, dict] = {}
    for m, proj, user in rows:
        p = result.setdefault(proj.id, {"project_id": proj.id, "project_name": proj.name, "persons": []})
        p["persons"].append({"id": user.id, "name": user.name, "is_default": m.is_default})
    return list(result.values())


@router.get("/priority-rules", response_model=list[PriorityRuleOut])
def list_priority_rules(db: Session = Depends(get_db)):
    return db.query(PriorityRule).order_by(PriorityRule.sort_order, PriorityRule.id).all()


@router.post("/priority-rules", response_model=PriorityRuleOut, status_code=201)
def add_priority_rule(body: PriorityRuleCreate, db: Session = Depends(get_db)):
    mx = db.query(PriorityRule).count()
    r = PriorityRule(pattern=body.pattern, label=body.label, priority=body.priority, sort_order=mx)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.delete("/priority-rules/{rule_id}", status_code=204)
def del_priority_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(PriorityRule, rule_id)
    if not r:
        raise HTTPException(404, "规则不存在")
    db.delete(r)
    db.commit()


@router.get("/sla", response_model=list[SLADefinitionOut])
def list_sla(db: Session = Depends(get_db)):
    return db.query(SLADefinition).order_by(SLADefinition.priority).all()


@router.get("/approval-flows", response_model=list[ApprovalFlowOut])
def list_approval_flows(db: Session = Depends(get_db)):
    return db.query(ApprovalFlow).filter(ApprovalFlow.enabled.is_(True)).order_by(ApprovalFlow.priority).all()


# ====== 解析规则 CRUD ======
@router.get("/parsing-rules", response_model=list[ParsingRuleOut])
def list_parsing_rules(db: Session = Depends(get_db)):
    return db.query(ParsingRule).order_by(ParsingRule.sort_order, ParsingRule.id).all()


class ParsingRuleCreate(BaseModel):
    name: str
    pattern: str
    weight: int = 1


@router.post("/parsing-rules", response_model=ParsingRuleOut, status_code=201)
def add_parsing_rule(body: ParsingRuleCreate, db: Session = Depends(get_db)):
    r = ParsingRule(name=body.name, pattern=body.pattern, weight=body.weight)
    db.add(r); db.commit(); db.refresh(r)
    return r


@router.patch("/parsing-rules/{rule_id}", response_model=ParsingRuleOut)
def update_parsing_rule(rule_id: int, enabled: bool | None = None, weight: int | None = None, db: Session = Depends(get_db)):
    r = db.get(ParsingRule, rule_id)
    if not r: raise HTTPException(404, "规则不存在")
    if enabled is not None: r.enabled = enabled
    if weight is not None: r.weight = weight
    db.commit(); db.refresh(r)
    return r


@router.delete("/parsing-rules/{rule_id}", status_code=204)
def del_parsing_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(ParsingRule, rule_id)
    if not r: raise HTTPException(404, "规则不存在")
    db.delete(r); db.commit()


# ====== 优先级规则更新 ======
@router.patch("/priority-rules/{rule_id}", response_model=PriorityRuleOut)
def update_priority_rule(rule_id: int, body: PriorityRuleUpdate, db: Session = Depends(get_db)):
    r = db.get(PriorityRule, rule_id)
    if not r: raise HTTPException(404, "规则不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items(): setattr(r, k, v)
    db.commit(); db.refresh(r)
    return r


# ====== SLA 更新 ======
class SLAUpdate(BaseModel):
    deadline_days: int | None = None
    warn_before_hours: int | None = None
    escalate_hours: float | None = None


@router.patch("/sla/{sla_id}", response_model=SLADefinitionOut)
def update_sla(sla_id: int, body: SLAUpdate, db: Session = Depends(get_db)):
    s = db.get(SLADefinition, sla_id)
    if not s: raise HTTPException(404, "SLA 不存在")
    if body.deadline_days is not None: s.deadline_days = body.deadline_days
    if body.warn_before_hours is not None: s.warn_before_hours = body.warn_before_hours
    if body.escalate_hours is not None: s.escalate_hours = body.escalate_hours
    db.commit(); db.refresh(s)
    return s


# ====== 工单类型 CRUD ======
@router.get("/work-order-types-full", response_model=list[WorkOrderTypeOut])
def list_wo_types_full(db: Session = Depends(get_db)):
    return db.query(WorkOrderTypeKB).order_by(WorkOrderTypeKB.sort_order).all()


@router.post("/work-order-types", response_model=WorkOrderTypeOut, status_code=201)
def add_wo_type(body: WorkOrderTypeCreate, db: Session = Depends(get_db)):
    mx = db.query(WorkOrderTypeKB).count()
    t = WorkOrderTypeKB(
        type_code=body.type_code, name=body.name, desc=body.desc,
        default_approver_id=body.default_approver_id,
        default_priority=body.default_priority, sort_order=mx,
        guidance_ref=body.guidance_ref,
        sop_purpose=body.sop_purpose,
        sop_scope=body.sop_scope,
        sop_steps=body.sop_steps,
        sop_acceptance=body.sop_acceptance,
        sop_backfill_required=body.sop_backfill_required,
        sop_escalation=body.sop_escalation,
        sop_related_guidance=body.sop_related_guidance,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


@router.patch("/work-order-types/{type_id}", response_model=WorkOrderTypeOut)
def update_wo_type(type_id: int, body: WorkOrderTypeUpdate, db: Session = Depends(get_db)):
    t = db.get(WorkOrderTypeKB, type_id)
    if not t: raise HTTPException(404, "类型不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(t, k, v)
    db.commit(); db.refresh(t)
    return t


@router.delete("/work-order-types/{type_id}", status_code=204)
def del_wo_type(type_id: int, db: Session = Depends(get_db)):
    t = db.get(WorkOrderTypeKB, type_id)
    if not t: raise HTTPException(404, "类型不存在")
    db.delete(t); db.commit()


# ====== 人员-项目映射 CRUD ======
@router.get("/person-project-map-full", response_model=list[PersonMapOut])
def list_person_map_full(db: Session = Depends(get_db)):
    rows = db.query(PersonProjectMap, Project, User).join(
        Project, PersonProjectMap.project_id == Project.id
    ).join(User, PersonProjectMap.user_id == User.id).all()
    out = []
    for m, proj, user in rows:
        out.append(PersonMapOut(id=m.id, project_id=m.project_id, user_id=m.user_id,
                                is_default=m.is_default, project_name=proj.name, user_name=user.name))
    return out


@router.post("/person-project-map", response_model=PersonMapOut, status_code=201)
def add_person_map(body: PersonMapCreate, db: Session = Depends(get_db)):
    m = PersonProjectMap(project_id=body.project_id, user_id=body.user_id, is_default=body.is_default)
    db.add(m); db.commit(); db.refresh(m)
    proj = db.get(Project, m.project_id); user = db.get(User, m.user_id)
    return PersonMapOut(id=m.id, project_id=m.project_id, user_id=m.user_id,
                        is_default=m.is_default, project_name=proj.name if proj else None,
                        user_name=user.name if user else None)


@router.delete("/person-project-map/{map_id}", status_code=204)
def del_person_map(map_id: int, db: Session = Depends(get_db)):
    m = db.get(PersonProjectMap, map_id)
    if not m: raise HTTPException(404, "映射不存在")
    db.delete(m); db.commit()


# ====== 来源/状态 (config_definitions) CRUD ======
@router.post("/config-definitions", response_model=ConfigDefinitionOut, status_code=201)
def add_config_def(body: ConfigDefCreate, db: Session = Depends(get_db)):
    mx = db.query(ConfigDefinition).filter_by(category=body.category).count()
    c = ConfigDefinition(category=body.category, code=body.code, name=body.name,
                         color=body.color, sort_order=mx)
    db.add(c); db.commit(); db.refresh(c)
    return c


@router.patch("/config-definitions/{def_id}", response_model=ConfigDefinitionOut)
def update_config_def(def_id: int, name: str | None = None, color: str | None = None,
                      db: Session = Depends(get_db)):
    c = db.get(ConfigDefinition, def_id)
    if not c: raise HTTPException(404, "配置不存在")
    if name is not None: c.name = name
    if color is not None: c.color = color
    db.commit(); db.refresh(c)
    return c


@router.delete("/config-definitions/{def_id}", status_code=204)
def del_config_def(def_id: int, db: Session = Depends(get_db)):
    c = db.get(ConfigDefinition, def_id)
    if not c: raise HTTPException(404, "配置不存在")
    db.delete(c); db.commit()


# ====== 审批流编辑 ======
class ApprovalFlowUpdate(BaseModel):
    name: str | None = None
    nodes: list | None = None
    escalation: dict | None = None


@router.patch("/approval-flows/{flow_id}", response_model=ApprovalFlowOut)
def update_approval_flow(flow_id: int, body: ApprovalFlowUpdate, db: Session = Depends(get_db)):
    f = db.get(ApprovalFlow, flow_id)
    if not f: raise HTTPException(404, "审批流不存在")
    if body.name is not None: f.name = body.name
    if body.nodes is not None: f.nodes = body.nodes
    if body.escalation is not None: f.escalation = body.escalation
    db.commit(); db.refresh(f)
    return f


# ====== 通知策略 CRUD ======
@router.get("/notification-policies", response_model=list[NotificationPolicyOut])
def list_notification_policies(db: Session = Depends(get_db)):
    return db.query(NotificationPolicy).order_by(NotificationPolicy.priority).all()


@router.post("/notification-policies", response_model=NotificationPolicyOut, status_code=201)
def add_notification_policy(body: NotificationPolicyCreate, db: Session = Depends(get_db)):
    p = NotificationPolicy(priority=body.priority, event=body.event, channels=body.channels, template=body.template)
    db.add(p); db.commit(); db.refresh(p)
    return p


@router.patch("/notification-policies/{policy_id}", response_model=NotificationPolicyOut)
def update_notification_policy(policy_id: int, channels: list | None = None, enabled: bool | None = None,
                               db: Session = Depends(get_db)):
    p = db.get(NotificationPolicy, policy_id)
    if not p: raise HTTPException(404, "策略不存在")
    if channels is not None: p.channels = channels
    if enabled is not None: p.enabled = enabled
    db.commit(); db.refresh(p)
    return p


@router.delete("/notification-policies/{policy_id}", status_code=204)
def del_notification_policy(policy_id: int, db: Session = Depends(get_db)):
    p = db.get(NotificationPolicy, policy_id)
    if not p: raise HTTPException(404, "策略不存在")
    db.delete(p)
    db.commit()


# ── 项目管理 CRUD ─────────────────────────────────────

from pydantic import BaseModel as PydanticBase, field_validator
from datetime import date

from app.services.region_map import normalize_region


def _maybe_trigger_judgment_meeting(project_id: int) -> None:
    """项目入场日期+产品系列确定后，异步触发判定会自动建会（失败不影响项目保存）"""
    try:
        from app.tasks import create_judgment_meeting_task
        create_judgment_meeting_task.delay(project_id)
    except Exception as e:
        print(f"[config] 触发判定会建会失败: {e}")


class ProjectCreate(PydanticBase):
    code: str
    name: str
    type: str | None = None
    region: str | None = None
    entry_date: date | None = None
    product_series: str | None = None

    @field_validator("region")
    @classmethod
    def _norm_region(cls, v: str | None) -> str | None:
        return normalize_region(v)


class ProjectUpdate(PydanticBase):
    name: str | None = None
    type: str | None = None
    region: str | None = None
    is_active: bool | None = None
    entry_date: date | None = None
    product_series: str | None = None

    @field_validator("region")
    @classmethod
    def _norm_region(cls, v: str | None) -> str | None:
        return normalize_region(v)

@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    if db.query(Project).filter(Project.code == body.code).first():
        raise HTTPException(409, "项目编码已存在")
    p = Project(code=body.code, name=body.name, type=body.type, region=body.region,
                entry_date=body.entry_date, product_series=body.product_series)
    db.add(p)
    db.commit()
    db.refresh(p)
    _maybe_trigger_judgment_meeting(p.id)
    return p

@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, "项目不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    _maybe_trigger_judgment_meeting(p.id)
    return p

@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, "项目不存在")
    p.is_active = False
    db.commit()


# ── 操作日志 ──────────────────────────────────────────

@router.get("/audit-logs")
def list_audit_logs(page: int = 1, page_size: int = 50, db: Session = Depends(get_db)):
    from app.models.audit import AuditLog
    total = db.query(AuditLog).count()
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return {
        "items": [{"id": r.id, "action": r.action, "target": r.target, "target_id": r.target_id,
                    "detail": r.detail, "operator": r.operator, "created_at": r.created_at.isoformat()} for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }


# ── 区域 PMO 配置 ──────────────────────────────────────

@router.get("/region-pmos", response_model=list[RegionPMOOut])
def list_region_pmos(db: Session = Depends(get_db)):
    """列出所有区域 PMO 映射"""
    rows = db.query(RegionPMO).order_by(RegionPMO.id).all()
    result = []
    for r in rows:
        user = db.get(User, r.user_id)
        result.append(RegionPMOOut(
            id=r.id, region=r.region, user_id=r.user_id,
            user_name=user.name if user else None,
        ))
    return result


@router.post("/region-pmos", response_model=RegionPMOOut, status_code=201)
def set_region_pmo(body: RegionPMOCreate, db: Session = Depends(get_db)):
    """设置区域 PMO（如果区域已存在则更新）"""
    existing = db.query(RegionPMO).filter(RegionPMO.region == body.region).first()
    if existing:
        existing.user_id = body.user_id
        db.commit()
        db.refresh(existing)
        r = existing
    else:
        r = RegionPMO(region=body.region, user_id=body.user_id)
        db.add(r)
        db.commit()
        db.refresh(r)
    user = db.get(User, r.user_id)
    return RegionPMOOut(id=r.id, region=r.region, user_id=r.user_id,
                        user_name=user.name if user else None)


@router.delete("/region-pmos/{pmo_id}", status_code=204)
def delete_region_pmo(pmo_id: int, db: Session = Depends(get_db)):
    """删除区域 PMO 映射"""
    r = db.get(RegionPMO, pmo_id)
    if not r:
        raise HTTPException(404, "区域PMO不存在")
    db.delete(r)
    db.commit()


# ── 组织角色 → 人员配置（审批流用角色，人名可后台改） ──

@router.get("/role-assignments", response_model=list[RoleAssignmentOut])
def list_role_assignments(db: Session = Depends(get_db)):
    """列出组织角色 → 人员映射"""
    rows = db.query(RoleAssignment).order_by(RoleAssignment.sort_order, RoleAssignment.id).all()
    out = []
    for r in rows:
        user = db.get(User, r.user_id) if r.user_id else None
        out.append(RoleAssignmentOut(
            id=r.id, role_code=r.role_code, role_name=r.role_name,
            user_id=r.user_id, user_name=user.name if user else None,
            sort_order=r.sort_order,
        ))
    return out


@router.patch("/role-assignments/{role_code}", response_model=RoleAssignmentOut)
def update_role_assignment(role_code: str, body: RoleAssignmentUpdate, db: Session = Depends(get_db)):
    """配置某角色由哪个人员担任"""
    r = db.query(RoleAssignment).filter(RoleAssignment.role_code == role_code).first()
    if not r:
        raise HTTPException(404, "角色不存在")
    if body.user_id is not None:
        if not db.get(User, body.user_id):
            raise HTTPException(404, "人员不存在")
        r.user_id = body.user_id
        db.commit()
        db.refresh(r)
    user = db.get(User, r.user_id) if r.user_id else None
    return RoleAssignmentOut(
        id=r.id, role_code=r.role_code, role_name=r.role_name,
        user_id=r.user_id, user_name=user.name if user else None,
        sort_order=r.sort_order,
    )
