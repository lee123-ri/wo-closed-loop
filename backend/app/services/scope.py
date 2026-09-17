"""行级数据范围（谁能看哪些工单）。

按当前用户身份逐级判定：
- admin                                     → 全部工单
- 区域 PMO（region_pmos 里配置了该 user）      → 其负责区域的工单 + 本人作为责任人/审批人的工单（含跨区域被派的单）
- 其他（executor / approver / readonly）      → 本人相关（任责任人 person_id 或审批人 approver_id）

调用方通过 apply_scope_to_query 把范围落到工单查询上；admin 原样返回查询不变。
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import RegionPMO, User, WorkOrder


def visible_scope(db: Session, user: User | None) -> dict | None:
    """返回数据范围描述；None 表示「不限（admin 超管）」."""
    if user is None or user.role == "admin":
        return None
    regions = [
        r.region
        for r in db.query(RegionPMO).filter(RegionPMO.user_id == user.id).all()
        if r.region
    ]
    if regions:
        return {"regions": regions}
    return {"self": True}


def apply_scope_to_query(q, db: Session, user: User | None):
    """把行级范围落到 query 上；admin 原样返回，不附加任何过滤."""
    scope = visible_scope(db, user)
    if scope is None:
        return q
    # 本人相关：任责任人 / 审批人（区域 PMO 也永远能看到自己被派的单，不受区域边界限制）
    self_cond = or_(WorkOrder.person_id == user.id, WorkOrder.approver_id == user.id)
    if "regions" in scope:
        return q.where(or_(WorkOrder.region.in_(scope["regions"]), self_cond))
    return q.where(self_cond)