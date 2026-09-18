"""通知规则模块：先试算，再由显式启用的规则投递两种机器人渠道。"""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models import NotificationLog, NotificationRule, OperationEvent, Project, User, WorkOrder
from app.services import dingtalk
from app.services.operation_events import record_event

ALLOWED_CHANNELS = frozenset(("robot_private", "robot_group"))

def _matches(rule: NotificationRule, wo: WorkOrder) -> bool:
    c = rule.conditions or {}
    return all(not c.get(key) or getattr(wo, key, None) in c[key] for key in ("priority", "status", "source_code", "region"))

def _recipient_users(db: Session, rule: NotificationRule, wo: WorkOrder) -> list[User]:
    spec = rule.recipients or {}
    ids = list(spec.get("user_ids") or [])
    if spec.get("responsible") and wo.person_id: ids.append(wo.person_id)
    if spec.get("approver") and wo.approver_id: ids.append(wo.approver_id)
    return db.query(User).filter(User.id.in_(set(ids)), User.is_active.is_(True)).all() if ids else []

def preview(db: Session, wo: WorkOrder, event: str, rule_ids: set[int] | None = None) -> list[dict]:
    rows = db.query(NotificationRule).filter(NotificationRule.event == event, NotificationRule.enabled.is_(True)).all()
    result=[]
    for rule in rows:
        if rule_ids is not None and rule.id not in rule_ids: continue
        if not _matches(rule, wo): continue
        users=_recipient_users(db, rule, wo)
        project=db.get(Project, wo.project_id) if wo.project_id else None
        result.append({"rule_id":rule.id,"rule_name":rule.name,"channels":rule.channels,"users":[{"id":u.id,"name":u.name} for u in users],"group_id":(rule.recipients or {}).get("group_id") or (project.dingtalk_group_id if project else None)})
    return result

def _is_in_cooldown(db: Session, rule: NotificationRule, wo: WorkOrder, event: str) -> bool:
    if not rule.cooldown_minutes:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=rule.cooldown_minutes)
    return db.query(NotificationLog).filter(NotificationLog.work_order_id == wo.id,
        NotificationLog.event == event, NotificationLog.created_at >= cutoff).first() is not None


def dispatch(db: Session, wo: WorkOrder, event: str, *, dry_run: bool = True, rule_ids: set[int] | None = None) -> dict:
    plans=preview(db,wo,event,rule_ids)
    if dry_run:
        record_event(db,category="notification",status="skipped",summary="通知规则试算",detail={"event":event,"plans":plans},work_order_id=wo.id)
        return {"dry_run":True,"plans":plans}
    sent=failed=0
    for plan in plans:
        rule=db.get(NotificationRule,plan["rule_id"])
        if _is_in_cooldown(db, rule, wo, event):
            record_event(db,category="notification",status="skipped",summary="通知处于冷却期",detail={"event":event,"cooldown_minutes":rule.cooldown_minutes},work_order_id=wo.id,notification_rule_id=rule.id)
            continue
        text=(rule.template or "工单 {code}：{title}").format(code=wo.code,title=wo.title,status=wo.status)
        for channel in rule.channels:
            if channel == "robot_private":
                for u in plan["users"]:
                    user=db.get(User,u["id"]); ok=bool(user and user.dingtalk_id and dingtalk.send_work_notification(user.dingtalk_id,rule.name,text))
                    db.add(NotificationLog(work_order_id=wo.id,channel=channel,recipient=user.dingtalk_id if user else "",event=event,status="sent" if ok else "failed",message=text)); sent+=int(ok); failed+=int(not ok)
            elif channel == "robot_group":
                group_id=plan["group_id"]
                ok=dingtalk.send_group_markdown(text, rule.name, group_id=group_id) if group_id else False
                db.add(NotificationLog(work_order_id=wo.id,channel=channel,recipient=group_id or "",event=event,status="sent" if ok else "failed",message=text)); sent+=int(ok); failed+=int(not ok)
        record_event(db,category="notification",status="success" if not failed else "failed",summary="机器人通知投递",detail={"event":event,"sent":sent,"failed":failed},work_order_id=wo.id,notification_rule_id=rule.id)
    return {"dry_run":False,"sent":sent,"failed":failed,"plans":plans}
