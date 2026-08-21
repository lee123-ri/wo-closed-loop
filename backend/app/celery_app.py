"""Celery 应用配置：异步任务 + 定时任务（SLA 扫描、升级检查）。"""
from celery import Celery

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
    "no-dispatch-sync": {
        "task": "app.tasks.sync_no_dispatch_records",
        "schedule": 600.0,  # 每 10 分钟补偿写不发现场关闭台账
    },
    "daily-reminder": {
        "task": "app.tasks.daily_reminder",
        "schedule": 1800.0,  # 每30分钟检查（仅9:00-9:59执行）
    },
}
