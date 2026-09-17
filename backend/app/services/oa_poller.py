"""OA 审批状态自动轮询（主动拉取，兜底钉钉 push 推送不可靠）。

钉钉事件推送目前不稳定，用主动轮询兜底：每 N 秒遍历一遍所有「有真实 OA 单且未闭环」的工单，
拉取钉钉最新状态 / 表单内容 / 附件并同步回平台。挂在 FastAPI lifespan 的后台 asyncio 任务上。
"""
import asyncio
from datetime import datetime

_task = None


def sync_all_live_oa() -> int:
    """遍历所有 live OA 工单，拉取最新状态/内容/附件。返回处理条数。"""
    from app.core.database import SessionLocal
    from app.models import WorkOrder
    from app.services.oa_event import apply_oa_event

    db = SessionLocal()
    try:
        wos = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.oa_id.isnot(None),
                ~WorkOrder.oa_id.like("OA-%"),
                ~WorkOrder.status.in_(["closed", "rejected"]),
            )
            .all()
        )
        n = 0
        for wo in wos:
            try:
                apply_oa_event({"processInstanceId": wo.oa_id}, db, event_type="自动轮询")
                n += 1
            except Exception as e:  # noqa: BLE001
                print(f"[oa-poll] 工单 {wo.id} 同步异常: {e}", flush=True)
        return n
    finally:
        db.close()


async def poll_oa_loop(interval: int = 30):
    """后台轮询循环。interval 秒一轮。"""
    while True:
        try:
            n = await asyncio.to_thread(sync_all_live_oa)
            if n:
                print(f"[oa-poll] 已轮询 {n} 个 OA 工单 @ {datetime.now().strftime('%H:%M:%S')}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[oa-poll] 轮询异常: {e}", flush=True)
        await asyncio.sleep(interval)


def start(interval: int = 30) -> "asyncio.Task | None":
    """在 lifespan 里启动轮询任务。"""
    global _task
    if _task is not None and not _task.done():
        return _task
    _task = asyncio.create_task(poll_oa_loop(interval))
    print(f"[oa-poll] OA 自动轮询已启动（每 {interval}s 一次）", flush=True)
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