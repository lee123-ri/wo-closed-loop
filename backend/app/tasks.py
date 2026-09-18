"""Celery 异步任务定义。"""
from app.celery_app import celery_app
from app.services.notification_service import send_notification
from app.services.approval_engine import run_escalation_scan


@celery_app.task(name="app.tasks.send_notification")
def send_notification_task(wo_id: int, event: str):
    """异步发送工单通知"""
    return send_notification(wo_id, event)


@celery_app.task(name="app.tasks.send_dispatch_group")
def send_dispatch_group_task(wo_ids: list[int]):
    """异步：把一批派发工单按责任人合并发群。"""
    from app.services.notification_service import send_dispatch_group
    return send_dispatch_group(wo_ids)


@celery_app.task(name="app.tasks.send_measure_dispatch")
def send_measure_dispatch_task(host_id: int, measure_ids: list[int]):
    """异步：措施工单派发后通报（突出完成人）。"""
    from app.services.notification_service import notify_measure_dispatch
    return notify_measure_dispatch(host_id, measure_ids)


def run_sla_scan(notify: bool = True) -> dict:
    """SLA 扫描（纯逻辑，进程内或 Celery 均可调）：检查即将到期和已违约的工单。

    遍历非闭环工单：
      距截止 ≤ 24h  → sla_warn（到期预警）
      已过截止      → 标 overdue + sla_breach（违约）
      overdue ≥ 72h → sla_breach_72h（严重违约）

    notify=False 时只更新工单逾期状态/预警统计，不发送通知：供本地进程内轮询兜底使用，
    避免开发环境误把真实钉钉通知发出去；生产走 Celery beat 时保持 notify=True。
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
                    if notify:
                        send_notification_task.delay(wo.id, "sla_breach")
                    breached += 1
                elif overdue_days >= 3 and (wo.overdue_days or 0) < 3:
                    # 超期3天，升级
                    wo.overdue_days = overdue_days
                    db.commit()
                    if notify:
                        send_notification_task.delay(wo.id, "sla_breach_72h")
                    breached_72h += 1

            # 24h内到期预警
            elif delta <= 1 and wo.status not in ("overdue", "closed"):
                if notify:
                    send_notification_task.delay(wo.id, "sla_warn")
                warned += 1
    finally:
        db.close()
    return {"warned": warned, "breached": breached, "breached_72h": breached_72h}


@celery_app.task(name="app.tasks.sla_scan")
def sla_scan():
    """定时 SLA 扫描（Celery beat 每 5 分钟触发，等价于进程内 run_sla_scan）"""
    return run_sla_scan()


@celery_app.task(name="app.tasks.escalation_scan")
def escalation_scan():
    """定时升级扫描"""
    return run_escalation_scan()


@celery_app.task(name="app.tasks.sync_aitable_plan")
def sync_aitable_plan():
    """定时从 AI 表格同步非EAM工单到数据池"""
    from app.services.aitable import sync_anomaly_to_pool
    return sync_anomaly_to_pool(full=False)


@celery_app.task(name="app.tasks.sync_aitable_full")
def sync_aitable_full():
    """全量同步 AI 表格数据"""
    from app.services.aitable import sync_anomaly_to_pool
    return sync_anomaly_to_pool(full=True)


@celery_app.task(name="app.tasks.sync_anomaly_daily")
def sync_anomaly_daily():
    """10:00/15:00 增量采集。正式上线默认只进入数据池，不自动生成工单。"""
    from app.core.config import get_settings
    if not get_settings().auto_workorder_import_enabled:
        return {"skipped": True, "reason": "正式上线默认人工勾选导入", "generated": 0}
    from app.services.aitable import run_anomaly_daily_sync
    return run_anomaly_daily_sync()


@celery_app.task(name="app.tasks.sync_plan_draft")
def sync_plan_draft():
    """轮询钉盘直导仅在明确开启自动导入后运行。"""
    from app.core.config import get_settings
    if not get_settings().auto_workorder_import_enabled:
        return {"skipped": True, "reason": "正式上线默认人工勾选导入"}
    from app.services.drive_workorder_import import import_drive_workorder_versions
    return import_drive_workorder_versions()


@celery_app.task(name="app.tasks.dispatch_monthly_plan_oa")
def dispatch_monthly_plan_oa():
    """每月 1 日 09:00 自动给「计划开始日在当月」且必填完整的计划工单发起 OA。"""
    from app.services.plan_dispatch import dispatch_monthly_plans
    return dispatch_monthly_plans()


@celery_app.task(name="app.tasks.sweep")
def sweep():
    """主动巡检：扫描静默失效（缺字段待派发/同步中断），发现即告警。"""
    from app.services.health_sweep import sweep_once
    return sweep_once()


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
            f"## 📋 工单每日简报 ({today.strftime('%m/%d')})",
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

        # 发送到群机器人（webhook 未配置时 send_robot_group 内部走 mock 打印并返回 False）
        from app.core.config import get_settings
        _cfg = get_settings()
        sent = dingtalk.send_robot_group(_cfg.dingtalk_robot_webhook, _cfg.dingtalk_robot_secret, "📋 工单每日简报", msg)
        if not sent:
            print(f"[daily-reminder] 群机器人未配置或发送失败，简报如下:\n{msg}")

        return {"total": total, "overdue": len(overdue), "due_soon": len(due_soon)}
    finally:
        db.close()
