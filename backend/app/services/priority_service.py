"""优先级判定服务：按规则正则匹配 + 优先级归一化"""
import re

from sqlalchemy.orm import Session

from app.models import PriorityRule


def normalize_priority(value) -> str | None:
    """把各种优先级写法归一化为 P1/P2/P3。无法识别返回 None。"""
    if value is None:
        return None
    s = str(value).strip().upper()
    s = {"1": "P1", "2": "P2", "3": "P3", "高": "P1", "中": "P2", "低": "P3"}.get(s, s)
    return s if s in ("P1", "P2", "P3") else None


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
