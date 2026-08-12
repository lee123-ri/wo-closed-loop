"""通知引擎：按优先级×事件查策略、解析通道、多通道发送。

事件类型：dispatch | unread | sla_warn | sla_breach | sla_breach_72h
通道：work_notify | app_ding | phone_ding | robot_mention | sms
"""
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import NotificationPolicy, NotificationLog, WorkOrder, User
from app.services import dingtalk


def resolve_channels(db: Session, priority: str, event: str) -> list[str]:
    """查通知策略，返回通道列表"""
    p = (
        db.query(NotificationPolicy)
        .filter(
            NotificationPolicy.priority == priority,
            NotificationPolicy.event == event,
            NotificationPolicy.enabled.is_(True),
        )
        .first()
    )
    if not p or not p.channels:
        return []
    return list(p.channels)


def build_message(wo: WorkOrder, event: str, db: Session) -> tuple[str, str]:
    """构造通知标题和正文"""
    title_map = {
        "dispatch": f"📌 新工单待处理 · {wo.code}",
        "unread": f"⏰ 工单 24h 未读提醒 · {wo.code}",
        "sla_warn": f"⚠️ 工单 SLA 即将到期 · {wo.code}",
        "sla_breach": f"🚨 工单 SLA 已违约 · {wo.code}",
        "sla_breach_72h": f"🚨🚨 工单违约超 72h · {wo.code}",
    }
    title = title_map.get(event, f"工单通知 · {wo.code}")
    person = db.get(User, wo.person_id) if wo.person_id else None
    approver = db.get(User, wo.approver_id) if wo.approver_id else None
    body = (
        f"**标题**：{wo.title}\n\n"
        f"**责任人**：{person.name if person else '—'}\n"
        f"**审批人**：{approver.name if approver else '—'}\n"
        f"**优先级**：{wo.priority}\n"
        f"**截止**：{wo.deadline}\n"
        f"**状态**：{wo.status}\n"
    )
    if wo.escalation_level > 0:
        body += f"**升级级别**：L{wo.escalation_level}\n"
    if event == "sla_breach" and wo.overdue_days:
        body += f"\n⚠️ 已超期 {wo.overdue_days} 天\n"
    return title, body


def send_notification(wo_id: int, event: str) -> dict:
    """同步发送通知（也可被 Celery 调用）"""
    db = SessionLocal()
    sent = 0
    failed = 0
    try:
        wo = db.get(WorkOrder, wo_id)
        if not wo:
            return {"error": "work order not found"}
        channels = resolve_channels(db, wo.priority, event)
        title, body = build_message(wo, event, db)
        person = db.get(User, wo.person_id) if wo.person_id else None
        approver = db.get(User, wo.approver_id) if wo.approver_id else None
        # 钉钉 userId（这里用 name 占位，真实场景需 user.dingtalk_id 映射）
        person_dt = (person.dingtalk_id or person.name) if person else ""
        approver_dt = (approver.dingtalk_id or approver.name) if approver else ""

        for ch in channels:
            ok = False
            log_ch = ch
            recipient = person_dt
            if ch == "work_notify" and person_dt:
                ok = dingtalk.send_work_notification(person_dt, title, body, action_url=f"/work-orders/{wo.id}")
            elif ch == "app_ding" and person_dt:
                ok = dingtalk.send_work_notification(person_dt, f"[应用DING]{title}", body)
            elif ch == "phone_ding" and person_dt:
                ok = dingtalk.send_phone_ding(person_dt, f"{title} {body}")
            elif ch == "robot_mention":
                # 群机器人（webhook 需配置，此处占位）
                ok = dingtalk.send_robot_group("", "", title, body, at_userids=[person_dt] if person_dt else [])
                recipient = "group"
            elif ch == "sms" and person and person.phone:
                # 短信通道占位
                print(f"[sms-mock] -> {person.phone}: {title}")
                ok = True
                log_ch = "sms"

            db.add(NotificationLog(
                work_order_id=wo.id, channel=log_ch, recipient=recipient,
                event=event, status="sent" if ok else "failed", message=title,
            ))
            if ok:
                sent += 1
            else:
                failed += 1
        db.commit()
    finally:
        db.close()
    return {"event": event, "sent": sent, "failed": failed}
