"""组织角色 → 人员解析。

审批流节点的 role 字段存角色编码（division_head/pmo/delivery_pmo），
具体由哪个人员担任该角色，通过 role_assignments 表配置，可在后台改。
"""
from sqlalchemy.orm import Session

from app.models import RoleAssignment, User


def resolve_role(db: Session, role_code: str | None) -> User | None:
    """按角色编码解析当前担任该角色的人员。无映射或无人员时返回 None。"""
    if not role_code:
        return None
    ra = (
        db.query(RoleAssignment)
        .filter(RoleAssignment.role_code == role_code)
        .first()
    )
    if not ra or not ra.user_id:
        return None
    return db.get(User, ra.user_id)


def resolve_role_user_id(db: Session, role_code: str | None) -> int | None:
    u = resolve_role(db, role_code)
    return u.id if u else None


# 节点 role → OA 审批阶段（用来映射钉钉单模板的 3 个审批节点）
#   approve=审批节点（执行前所有审批角色），execute=执行，accept=验收确认
_APPROVE_ROLES = {"pmo", "division_head", "delivery_pmo"}


def _node_stage(role: str) -> str:
    if role == "executor":
        return "execute"
    if role == "approver":
        return "accept"
    # pmo / division_head / delivery_pmo 及其它审批类角色 → approve
    return "approve"


def _resolve_node_user(db: Session, wo, role: str):
    """按节点 role 解析人员：角色编码走 role_assignments，特殊 token 走工单关联人。"""
    if role in _APPROVE_ROLES:
        return resolve_role(db, role)
    if role == "executor":
        return db.get(User, wo.person_id) if wo.person_id else None
    if role == "approver":
        return db.get(User, wo.approver_id) if wo.approver_id else None
    # creator：工单无 creator 字段，发起人暂用责任人兜底（后续要精确需加 creator 列）
    return db.get(User, wo.person_id) if wo.person_id else None


def resolve_oa_chain(db: Session, wo) -> list[dict]:
    """解析工单审批流角色链 → 具体审批人，供发起钉钉 OA 与回调路由复用。

    返回 [{stage, role, title, user_id, dingtalk_id, approved}]，按审批流节点顺序；
    stage ∈ approve/execute/accept。用户无钉钉 userId 时用姓名兜底（与
    dingtalk._lookup_dingtalk_id 一致）；节点解析不到人则跳过并打日志。
    P1 链=[approve:pmo, approve:division_head, execute:executor, accept:approver]
    P2 链=[approve:pmo, execute:executor, accept:approver]
    P3 链=[approve:pmo, execute:executor]
    """
    # 懒加载，避免与 approval_engine 的循环 import
    from app.services.approval_engine import get_flow

    flow = get_flow(db, wo.priority)
    chain: list[dict] = []
    if not flow or not flow.nodes:
        return chain

    for node in flow.nodes:
        if node.get("type") in ("start", "end"):
            continue
        role = node.get("role") or ""
        user = _resolve_node_user(db, wo, role)
        if not user:
            print(f"[roles] OA 链跳过节点 role={role or node.get('type')}: 无对应人员")
            continue
        chain.append({
            "stage": _node_stage(role),
            "role": role,
            "title": node.get("title") or role,
            "user_id": user.id,
            "dingtalk_id": user.dingtalk_id or user.name or "",
            "approved": False,
        })
    return chain