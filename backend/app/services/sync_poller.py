"""数据同步轮询（本地开发兜底；生产用 Celery beat）。

本地开发通常只起 uvicorn，不起 Celery beat，这里把两类同步挂到 FastAPI lifespan 的后台 asyncio 任务上：
1. 异常指标：汇总表 → 数据池 → 生成工单 + 双细则异常 → 直导工单，每 anomaly_sync_interval 秒跑一次增量，
   幂等（source_ref / client_request_id 去重）。
2. 年度运营计划「初稿」非EAM：钉盘初稿文件夹 → 下载解析 → 导入工单(source=plan)，每 plan_sync_interval 秒
   轮询一次（见 drive_workorder_import.import_drive_workorder_versions，项目+标题去重，补空不补错）。
"""
import asyncio
from datetime import datetime


_task: "asyncio.Task | None" = None
_plan_task: "asyncio.Task | None" = None

# 健康状态（供 health_sweep 巡检判断「同步是否还活着」）
_last_sync_ok: "datetime | None" = None   # 异常指标同步最近一次成功时间
_last_plan_ok: "datetime | None" = None   # 计划初稿同步最近一次成功时间


def run_sync() -> dict:
    """执行一次异常指标增量同步（汇总表 + 双细则异常），幂等可高频调用。"""
    from app.services.aitable import run_anomaly_daily_sync

    return run_anomaly_daily_sync()


def run_plan_sync() -> dict:
    """执行一次年度运营计划初稿（非EAM）导入——下载钉盘初稿文件夹 xlsx 并落工单(source=plan)。"""
    from app.services.drive_workorder_import import import_drive_workorder_versions

    return import_drive_workorder_versions()


async def poll_sync_loop(interval: int = 300):
    """后台轮询循环：每 interval 秒跑一次异常指标增量同步。"""
    global _last_sync_ok
    while True:
        try:
            result = await asyncio.to_thread(run_sync)
            _last_sync_ok = datetime.now()
            print(f"[anomaly-sync-poll] {result} @ {datetime.now().strftime('%H:%M:%S')}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[anomaly-sync-poll] 同步异常: {e}", flush=True)
        await asyncio.sleep(interval)


async def poll_plan_loop(interval: int = 3600):
    """后台轮询循环：每 interval 秒跑一次年度运营计划初稿（非EAM）导入。"""
    global _last_plan_ok
    while True:
        try:
            result = await asyncio.to_thread(run_plan_sync)
            _last_plan_ok = datetime.now()
            print(f"[plan-sync-poll] {result} @ {datetime.now().strftime('%H:%M:%S')}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[plan-sync-poll] 同步异常: {e}", flush=True)
        await asyncio.sleep(interval)


def start(interval: int = 300, plan_interval: int = 3600) -> "asyncio.Task | None":
    """在 lifespan 里启动两类轮询任务。"""
    global _task, _plan_task
    if _task is None or _task.done():
        _task = asyncio.create_task(poll_sync_loop(interval))
        print(f"[anomaly-sync-poll] 异常指标同步已启动（每 {interval}s 增量轮询）", flush=True)
    if _plan_task is None or _plan_task.done():
        _plan_task = asyncio.create_task(poll_plan_loop(plan_interval))
        print(f"[plan-sync-poll] 年度运营计划初稿同步已启动（每 {plan_interval}s 轮询）", flush=True)
    return _task


def sync_health() -> dict:
    """返回两类同步的最近成功时间（None=从未成功），供 health_sweep 判断同步是否中断。"""
    return {"anomaly_last_ok": _last_sync_ok, "plan_last_ok": _last_plan_ok}


async def stop():
    """在 lifespan 关闭时停止轮询任务。"""
    global _task, _plan_task
    for t in (_task, _plan_task):
        if t is not None and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
    _task = None
    _plan_task = None