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
    """定时 SLA 扫描（每5分钟）：检查即将到期和已违约的工单，触发对应通知。

    遍历非闭环工单：
      距截止 ≤ 24h  → sla_warn（到期预警）
      已过截止      → 标 overdue + sla_breach（违约）
      overdue ≥ 72h → sla_breach_72h（严重违约）
    """
    from datetime import date
    from app.core.database import SessionLocal
    from app.models import WorkOrder
    db = SessionLocal()
    warned = breached = breached_72h = 0
    try:
        wos = (
            db.query(WorkOrder)
            .filter(~WorkOrder.status.in_(["closed", "rejected"]))
            .all()
        )
        today = date.today()
        for wo in wos:
            if not wo.deadline:
                continue
            delta = (wo.deadline - today).days

            # 已逾期
            if delta < 0:
                overdue_days = -delta
                if wo.status != "overdue":
                    wo.status = "overdue"
                    wo.overdue_days = overdue_days
                    db.commit()
                    send_notification_task.delay(wo.id, "sla_breach")
                    breached += 1
                elif overdue_days >= 3 and (wo.overdue_days or 0) < 3:
                    # 超期3天，升级
                    wo.overdue_days = overdue_days
                    db.commit()
                    send_notification_task.delay(wo.id, "sla_breach_72h")
                    breached_72h += 1

            # 24h内到期预警
            elif delta <= 1 and wo.status not in ("overdue", "closed"):
                send_notification_task.delay(wo.id, "sla_warn")
                warned += 1
    finally:
        db.close()
    return {"warned": warned, "breached": breached, "breached_72h": breached_72h}


@celery_app.task(name="app.tasks.escalation_scan")
def escalation_scan():
    """定时升级扫描"""
    return run_escalation_scan()


@celery_app.task(name="app.tasks.sync_aitable_plan")
def sync_aitable_plan():
    """定时从 AI 表格同步非EAM软工单到数据池"""
    from app.services.aitable import sync_anomaly_to_pool
    return sync_anomaly_to_pool(full=False)


@celery_app.task(name="app.tasks.sync_aitable_full")
def sync_aitable_full():
    """全量同步 AI 表格数据"""
    from app.services.aitable import sync_anomaly_to_pool
    return sync_anomaly_to_pool(full=True)


@celery_app.task(name="app.tasks.sync_no_dispatch_records")
def sync_no_dispatch_records():
    """补偿写「不发现场关闭台账」：扫描已关但未同步到 AITable 的工单，重试写入。

    权限未授予期间持续重试；权限到位后一次补齐全部 pending 记录。
    """
    from datetime import datetime
    from app.core.database import SessionLocal
    from app.models import WorkOrder, Project, DataPoolItem
    from app.services.aitable import write_no_dispatch_record

    db = SessionLocal()
    synced = pending = 0
    try:
        wos = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.closed_without_dispatch.is_(True),
                WorkOrder.no_dispatch_synced.is_(False),
                WorkOrder.no_dispatch_reason.isnot(None),
            )
            .all()
        )
        for wo in wos:
            pool = db.query(DataPoolItem).filter(DataPoolItem.id == wo.parent_pool_id).first() if wo.parent_pool_id else None
            raw = (pool.raw_data or {}) if pool else {}
            proj = db.get(Project, wo.project_id) if wo.project_id else None
            project_name = proj.name if proj else (pool.project_name if pool else None)
            anomaly_type = raw.get("anomaly_type") or raw.get("异常指标") or (pool.metric_type if pool else None) or ""
            month = raw.get("month") or raw.get("异常月份") or ""
            source = "agent_no_action" if wo.judgment_status == "no_action_needed" else "pmo_manual"
            data = {
                "标题": f"{project_name or ''}-{anomaly_type or wo.code}-不发现场",
                "工单编号": wo.code,
                "项目名称": project_name or "",
                "异常指标": str(anomaly_type) if anomaly_type else "",
                "异常月份": str(month) if month else "",
                "关闭原因": wo.no_dispatch_reason,
                "判断来源": source,
                "操作人": "",
                "操作时间": (wo.completed_date.strftime("%Y-%m-%d")
                            if wo.completed_date else datetime.now().strftime("%Y-%m-%d %H:%M")),
            }
            if write_no_dispatch_record(data):
                wo.no_dispatch_synced = True
                synced += 1
            else:
                pending += 1
        db.commit()
    finally:
        db.close()
    return {"synced": synced, "pending": pending}


@celery_app.task(name="app.tasks.daily_reminder")
def daily_reminder():
    """每日提醒：汇总所有活跃工单状态，发送群周报。

    每天早上 9:00 触发（通过 beat schedule 每小时检查，仅 9:00-9:59 执行一次）。
    """
    from datetime import datetime, date
    now = datetime.now()
    # 仅在早上 9:00-9:59 执行
    if now.hour != 9:
        return {"skipped": True, "reason": f"not 9am, current hour: {now.hour}"}

    from app.core.database import SessionLocal
    from app.models import WorkOrder
    from app.services import dingtalk

    db = SessionLocal()
    try:
        today = date.today()
        active = (
            db.query(WorkOrder)
            .filter(~WorkOrder.status.in_(["closed", "rejected"]))
            .all()
        )

        total = len(active)
        if total == 0:
            return {"skipped": True, "reason": "no active work orders"}

        overdue = [wo for wo in active if wo.status == "overdue"]
        due_soon = [
            wo for wo in active
            if wo.deadline and 0 <= (wo.deadline - today).days <= 1 and wo.status != "overdue"
        ]

        # 构建每日摘要
        lines = [
            f"## 📋 软工单每日简报 ({today.strftime('%m/%d')})",
            "",
            f"**活跃工单**: {total} 个",
        ]
        if overdue:
            lines.append(f"**🚨 已逾期**: {len(overdue)} 个")
            for wo in overdue[:5]:
                lines.append(f"  · {wo.code} {wo.title} (逾期{wo.overdue_days}天)")
        if due_soon:
            lines.append(f"**⚠️ 即将到期**: {len(due_soon)} 个")
            for wo in due_soon[:5]:
                lines.append(f"  · {wo.code} {wo.title} (截止{wo.deadline})")

        msg = "\n".join(lines)

        # 发送到群机器人（webhook 需配置）
        if dingtalk._configured():
            dingtalk.send_robot_group("", "", "📋 软工单每日简报", msg)
        else:
            print(f"[daily-reminder] 钉钉未配置，跳过发送:\n{msg}")

        return {"total": total, "overdue": len(overdue), "due_soon": len(due_soon)}
    finally:
        db.close()
