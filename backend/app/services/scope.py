"""行级数据范围（谁能看哪些工单）。

范围判定从「硬编码」改为「后台可配」：把人归到某个数据范围角色，再读
role_data_scopes 表里该角色的可见范围勾选（多选取并集，天然去重）：

- admin           → 锁死「全部」，不读配置、不受后台改动影响。
- 事业部 PMO/负责人 → 默认「全部」（后台可改）。
- 区域 PMO        → 默认「自己相关 + 区域」（后台可改；region 展开到其负责大区）。
- 未分配业务岗位的用户 → 默认「项目人员」，仅看自己相关（后台可改）。

管理范围走 apply_scope_to_query；「我的工单」严格个人范围走
apply_personal_scope_to_query（不受管理身份扩大）。
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import BusinessRole, BusinessRoleAssignment, RegionPMO, RoleAssignment, RoleDataScope, User, WorkOrder

# 可行可见范围（三档，可多选）
SCOPE_OPTIONS = ("self", "region", "all")
VALID_SCOPES = frozenset(SCOPE_OPTIONS)

# 兜底默认：role_data_scopes 缺行时保持旧行为，避免灌种子前误放量/误收紧。
DEFAULT_ROLE_SCOPES = {
    "admin": ["all"],
    "pmo": ["all"],
    "region_pmo": ["self", "region"],
    "regional_pmo": ["self", "region"],
    "regional_gm": ["self", "region"],
    "regional_deputy_gm": ["self", "region"],
    "project_member": ["self"],
    "site_member": ["self"],
    "inspection_engineer": ["self"],
    "project_manager": ["self"],
    "headquarters_member": ["self"],
    "member": ["self"],
}


def _scopes_for(db: Session, role_code: str) -> list[str]:
    """读某角色的可见范围勾选；行缺失或 scopes 为 NULL 时回退默认值，否则原样返回（含空集）。"""
    row = db.query(RoleDataScope).filter(RoleDataScope.role_code == role_code).first()
    if row is not None and row.scopes is not None:
        scopes = row.scopes
    else:
        scopes = DEFAULT_ROLE_SCOPES.get(role_code, ["self"])
    return [s for s in scopes if s in VALID_SCOPES]


def resolve_data_roles(db: Session, user: User | None) -> tuple[set[str], list[str]]:
    """返回用户业务岗位对应的数据范围角色及其负责区域。

    用户管理里的业务岗位是唯一的人员归属来源。旧的角色人员映射仅继续为
    既有审批流解析兜底，避免迁移时中断已配置的工单模板。
    """
    if user is None:
        return ({"project_member"}, [])
    if user.role == "admin":
        return ({"admin"}, [])
    business_codes = {
        role.code
        for _, role in (
            db.query(BusinessRoleAssignment, BusinessRole)
            .join(BusinessRole, BusinessRole.id == BusinessRoleAssignment.business_role_id)
            .filter(BusinessRoleAssignment.user_id == user.id, BusinessRole.is_active.is_(True))
            .all()
        )
    }
    regions = [
        r.region
        for r in db.query(RegionPMO).filter(RegionPMO.user_id == user.id).all()
        if r.region
    ]
    if business_codes:
        return (business_codes, regions)
    # 存量业务：尚未在用户列表分配业务岗位时，不改变已生效的数据范围。
    legacy_codes = {r.role_code for r in db.query(RoleAssignment).filter(RoleAssignment.user_id == user.id).all()}
    if legacy_codes & {"division_head", "pmo"}:
        return ({"pmo"}, regions)
    if regions:
        return ({"regional_pmo"}, regions)
    return ({"project_member"}, [])


def apply_scope_to_query(q, db: Session, user: User | None):
    """把行级数据范围落到 query 上。

    admin 锁死「全部」，原样返回不附加过滤；
    其余角色读 role_data_scopes 勾选，多选取 OR 并集（数据库天然去重）：
      self  → 本人为责任人/审批人
      region→ 工单所属大区 ∈ 我的负责大区（仅区域 PMO 有值）
      all  → 不限
    勾选为空集时显式返回无结果（避免意外放量）。
    """
    if user is None:
        return q
    if user.role == "admin":
        # 超管锁死全部：不读配置、不受后台改动影响。
        return q
    role_codes, regions = resolve_data_roles(db, user)
    scopes = {scope for role_code in role_codes for scope in _scopes_for(db, role_code)}
    if "all" in scopes:
        return q
    conds = []
    if "self" in scopes:
        conds.append(or_(WorkOrder.person_id == user.id, WorkOrder.approver_id == user.id))
    if "region" in scopes and regions:
        conds.append(WorkOrder.region.in_(regions))
    if not conds:
        return q.where(WorkOrder.id.is_(None))
    return q.where(or_(*conds))


def apply_personal_scope_to_query(q, user: User | None, role: str = "all"):
    """把查询限制为登录人作为责任人或审批人的工单。

    这是“我的工单”的产品范围，不继承管理员全量、区域 PMO 区域范围等
    管理权限；管理范围仍由 :func:`apply_scope_to_query` 处理。

    role 进一步收窄“本人关联”的细分：
    - all          责任人或审批人（默认）
    - responsible  仅本人为责任人
    - approver     仅本人为审批人
    - both         本人同时为责任人和审批人
    """
    if user is None:
        # 该分支不应出现在 require_auth 路由中；显式返回无结果而非意外放量。
        return q.where(WorkOrder.id.is_(None))
    if role == "responsible":
        return q.where(WorkOrder.person_id == user.id)
    if role == "approver":
        return q.where(WorkOrder.approver_id == user.id)
    if role == "both":
        return q.where(WorkOrder.person_id == user.id, WorkOrder.approver_id == user.id)
    return q.where(or_(WorkOrder.person_id == user.id, WorkOrder.approver_id == user.id))


PERSONAL_ROLES = ("all", "responsible", "approver", "both")
