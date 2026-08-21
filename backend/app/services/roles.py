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