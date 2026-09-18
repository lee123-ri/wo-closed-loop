"""Celery 应用配置：异步任务 + 定时任务（SLA 扫描、升级检查）。"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "wo_closed_loop",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_always_eager=(not settings.is_prod),  # 开发环境同步执行，无需起 worker
    task_default_queue="wo",
)

# 定时任务
celery_app.conf.beat_schedule = {
    "sla-scan": {
        "task": "app.tasks.sla_scan",
        "schedule": 300.0,  # 每 5 分钟
    },
    "escalation-scan": {
        "task": "app.tasks.escalation_scan",
        "schedule": 600.0,  # 每 10 分钟
    },
    "daily-reminder": {
        "task": "app.tasks.daily_reminder",
        "schedule": 1800.0,  # 每30分钟检查（仅9:00-9:59执行）
    },
    "dispatch-monthly-plan-oa": {
        "task": "app.tasks.dispatch_monthly_plan_oa",
        "schedule": crontab(minute=0, hour=9, day_of_month=1),  # 每月 1 日 09:00 自动派发当月计划
    },
    "sweep": {
        "task": "app.tasks.sweep",
        "schedule": 600.0,  # 每 10 分钟主动巡检：静默失效扫描 → 告警
    },
}

# 正式上线默认不自动从外部源建单，先由管理员在数据池逐条勾选。
if settings.auto_workorder_import_enabled:
    celery_app.conf.beat_schedule.update({
        "sync-anomaly-reason-workorders": {
            "task": "app.tasks.sync_anomaly_daily",
            "schedule": crontab(minute=0, hour="10,15"),
        },
        "sync-plan-draft": {
            "task": "app.tasks.sync_plan_draft",
            "schedule": 3600.0,
        },
    })
