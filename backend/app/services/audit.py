"""操作日志写入入口：关键操作统一落 audit_log 表。

调用方在同一事务里先 log_audit(...) 再 commit，保证「业务变更 + 日志」原子。
"""
import json

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def log_audit(db: Session, *, actor_id: int | None, action: str,
              target_type: str | None = None, target_id: int | None = None,
              detail: dict | None = None) -> None:
    """记录一条操作日志。detail 以 JSON 文本存，读接口原样返回。"""
    db.add(AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(detail, ensure_ascii=False) if detail is not None else None,
    ))
