"""SLA 扫描 + 升级扫描的进程内轮询（本地开发兜底；生产用 Celery beat）。

本地开发通常只起 uvicorn，不起 Celery worker/beat，导致「标逾期 → 升级告警」这条链路
没人跑，告警列（escalation_level）恒为 0。这里把同一套扫描逻辑挂到 FastAPI lifespan 的
后台 asyncio 任务上，每 N 秒跑一轮，等效 Celery beat 的 sla-scan + escalation-scan。

与生产语义的区别：此处以 notify=False 调用 run_sla_scan，只更新工单逾期状态与升级等级，
不发送钉钉通知——避免本地开发环境误把真实通知发出去。生产环境在 main.py 侧本模块不启用，
仍由 Celery beat 触发带通知的完整扫描。
"""
import asyncio
from datetime import datetime

_task = None


def run_once() -> dict:
    """跑一轮 SLA 扫描 + 升级扫描，返回汇总。"""
    from app.tasks import run_sla_scan
    from app.services.approval_engine import run_escalation_scan

    sla = run_sla_scan(notify=False)
    esc = run_escalation_scan()
    return {"sla": sla, "escalation": esc}


async def poll_sla_loop(interval: int = 300):
    """后台轮询循环。interval 秒一轮。"""
    while True:
        try:
            result = await asyncio.to_thread(run_once)
            print(f"[sla-poll] {result} @ {datetime.now().strftime('%H:%M:%S')}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[sla-poll] 扫描异常: {e}", flush=True)
        await asyncio.sleep(interval)


def start(interval: int = 300) -> "asyncio.Task | None":
    """在 lifespan 里启动轮询任务。"""
    global _task
    if _task is not None and not _task.done():
        return _task
    _task = asyncio.create_task(poll_sla_loop(interval))
    print(f"[sla-poll] SLA/升级扫描已启动（每 {interval}s 一轮，不发通知）", flush=True)
    return _task


async def stop():
    """在 lifespan 关闭时停止轮询任务。"""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None