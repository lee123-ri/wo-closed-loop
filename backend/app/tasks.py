"""Celery 异步任务定义。"""
from app.celery_app import celery_app
from app.services.notification_service import send_notification
from app.services.approval_engine import run_escalation_scan


@celery_app.task(name="app.tasks.send_notification")
def send_notification_task(wo_id: int, event: str):
    """异步发送工单通知"""
    return send_notification(wo_id, event)


@celery_app.task(name="app.tasks.sla_scan")
def sla_scan():
    """定时 SLA 扫描：检查即将到期和已违约的工单，触发对应通知。

    遍历非闭环工单：
      距截止 ≤ 24h → sla_warn
      已过截止且状态非 overdue → 标 overdue + sla_breach
    """
    from datetime import date
    from app.core.database import SessionLocal
    from app.models import WorkOrder
    db = SessionLocal()
    warned = breached = 0
    try:
        wos = db.query(WorkOrder).filter(~WorkOrder.status.in_(["closed", "rejected"])).all()
        today = date.today()
        for wo in wos:
            if not wo.deadline:
                continue
            delta = (wo.deadline - today).days
            if delta < 0 and wo.status != "overdue":
                wo.status = "overdue"
                wo.overdue_days = -delta
                db.commit()
                send_notification_task.delay(wo.id, "sla_breach")
                breached += 1
            elif delta == 0 and wo.status not in ("overdue",):
                # 当天到期预警
                send_notification_task.delay(wo.id, "sla_warn")
                warned += 1
    finally:
        db.close()
    return {"warned": warned, "breached": breached}


@celery_app.task(name="app.tasks.escalation_scan")
def escalation_scan():
    """定时升级扫描"""
    return run_escalation_scan()
