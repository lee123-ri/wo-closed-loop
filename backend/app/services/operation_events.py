"""运行事件的统一写入入口。"""
from sqlalchemy.orm import Session
from app.models import OperationEvent

def record_event(db: Session, *, category: str, status: str, summary: str, detail: dict | None = None,
                 trace_id: str | None = None, work_order_id: int | None = None, notification_rule_id: int | None = None) -> OperationEvent:
    event = OperationEvent(category=category, status=status, summary=summary, detail=detail,
                           trace_id=trace_id, work_order_id=work_order_id, notification_rule_id=notification_rule_id)
    db.add(event)
    return event
