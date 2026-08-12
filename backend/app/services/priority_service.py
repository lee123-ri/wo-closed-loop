"""优先级判定服务：按规则正则匹配"""
import re

from sqlalchemy.orm import Session

from app.models import PriorityRule


def match_priority(db: Session, text: str, source: str = "", wo_type: str = "") -> str:
    """按优先级规则顺序匹配，命中即停。返回 P1|P2|P3"""
    combined = f"{text or ''} {source or ''} {wo_type or ''}"
    rules = (
        db.query(PriorityRule)
        .filter(PriorityRule.enabled.is_(True))
        .order_by(PriorityRule.sort_order, PriorityRule.id)
        .all()
    )
    for r in rules:
        try:
            if re.search(r.pattern, combined, re.IGNORECASE):
                return r.priority
        except re.error:
            continue
    return "P3"
