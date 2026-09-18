"""组织事实转换为待确认岗位候选；这里绝不直接授予岗位。"""
from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models import BusinessRole, BusinessRoleAssignment, OrganizationMappingRule, OrganizationSyncCandidate


def confirm_candidate(db: Session, candidate: OrganizationSyncCandidate) -> BusinessRoleAssignment:
    role = db.query(BusinessRole).filter_by(code=candidate.business_role_code, is_active=True).first()
    if not role:
        raise ValueError("业务岗位不存在或已停用")
    row = db.query(BusinessRoleAssignment).filter_by(
        user_id=candidate.user_id, business_role_id=role.id,
        scope_type=candidate.scope_type, scope_id=candidate.scope_id,
    ).first()
    if row is None:
        row = BusinessRoleAssignment(user_id=candidate.user_id, business_role_id=role.id,
            scope_type=candidate.scope_type, scope_id=candidate.scope_id,
            source="dingtalk", is_confirmed=True)
        db.add(row)
        db.flush()
    candidate.status = "confirmed"
    return row


def build_candidates_from_directory(records: Iterable[dict], rules: Iterable[OrganizationMappingRule]) -> list[dict]:
    """根据管理员规则生成候选；匹配失败、规则停用均不产生隐式授权。"""
    enabled = [rule for rule in rules if rule.enabled]
    candidates: list[dict] = []
    for record in records:
        for rule in enabled:
            values = record.get(rule.source_kind, [])
            if isinstance(values, str):
                values = [values]
            for value in values or []:
                if re.search(rule.pattern, str(value), re.IGNORECASE):
                    candidates.append({"user_id": record["user_id"], "business_role_code": rule.business_role_code,
                        "scope_type": rule.scope_type, "scope_id": record.get("scope_id"),
                        "source_kind": rule.source_kind, "source_value": str(value), "confidence": 100})
                    break
    return candidates


def create_pending_candidate(db: Session, data: dict) -> tuple[OrganizationSyncCandidate, bool]:
    """幂等写待确认候选；已确认的事实不被同步覆盖。"""
    row = db.query(OrganizationSyncCandidate).filter_by(
        user_id=data["user_id"], business_role_code=data["business_role_code"],
        scope_type=data.get("scope_type", "global"), scope_id=data.get("scope_id"),
        source_kind=data["source_kind"], source_value=data["source_value"],
    ).first()
    if row:
        return row, False
    row = OrganizationSyncCandidate(**data)
    db.add(row)
    db.flush()
    return row, True
