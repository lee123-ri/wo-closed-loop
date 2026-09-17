"""主动巡检（静默失效扫描）：周期性发现「系统该做没做」的故障并告警。

为什么要有它
------------
有些故障是「静默」的——没人点按钮就不会暴露，例如：
- 措施工单已生成但缺 OA 必填字段，一直躺在「待派发」里，等有人点「派发」才 422；
- 异常指标/计划同步悄悄停了，新工单不再进来，但没人知道。

巡检每 SWEEP_INTERVAL 秒扫一遍，发现问题即汇总成一条告警单发给负责人，逐项附修复动作。

检查项（本轮）
--------------
1. 待派发(pending)却缺 OA 必填字段的工单——派发会被 422 拦截的元凶。
2. 异常指标 / 计划初稿同步超过 3×interval 没有成功（读 sync_poller 健康状态）。

运行方式
--------
本地（dev）：main.py 的 lifespan 起进程内轮询；生产：由 Celery beat 调 run_sweep()。
注意：生产下 sync_poller 不跑（同步走 Celery beat），「同步中断」检查仅对本地 dev 生效，
生产侧同步健康检查后续再补（用 DB 记录 last_success 更通用）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import get_logger

log = get_logger(__name__)
settings = get_settings()

_task: "asyncio.Task | None" = None
_last_run_at: "datetime | None" = None


def run_sweep() -> dict:
    """执行一轮巡检，返回 {scanned_at, problems:[{kind, summary, detail, fix}]}。"""
    problems: list[dict] = []
    db = SessionLocal()
    try:
        problems += _scan_missing_oa_fields(db)
    except Exception as e:  # 单项失败不影响整体
        log.error("[sweep] 扫描缺 OA 必填字段失败: %s", e, exc_info=True)
    finally:
        db.close()

    problems += _scan_sync_stall()

    return {"scanned_at": datetime.now().isoformat(timespec="seconds"), "problems": problems}


def _scan_missing_oa_fields(db) -> list[dict]:
    """扫待派发工单里缺 OA 必填字段的（派发会被 422 拦截）。"""
    from app.models import WorkOrder
    from app.services.dingtalk import oa_required_missing

    candidates = db.query(WorkOrder).filter(WorkOrder.status == "pending").all()
    bad: list[tuple[WorkOrder, list[str]]] = []
    for wo in candidates:
        miss = oa_required_missing(wo)
        if miss:
            bad.append((wo, miss))
    if not bad:
        return []

    rows = "、".join(f"{wo.code}缺{'/'.join(miss)}" for wo, miss in bad[:20])
    more = f"… 等共 {len(bad)} 条" if len(bad) > 20 else ""
    return [{
        "kind": "missing_oa_fields",
        "summary": f"{len(bad)} 条待派发工单缺 OA 必填字段",
        "detail": f"这些工单派发/发起 OA 时会被 422 拦截：{rows}{more}",
        "fix": "去工单详情补齐缺失的责任人/审批人/计划开始时间/截止时间/触发原因/行动要求；"
               "若大量异常主单都缺责任人，优先核对「异常大类默认责任人」规则配置",
    }]


def _scan_sync_stall() -> list[dict]:
    """扫同步是否中断（最近成功时间超过 3×interval 仍未更新）。仅本地 dev 有效。"""
    try:
        from app.services import sync_poller

        health = sync_poller.sync_health()
    except Exception:
        return []

    now = datetime.now()
    probs: list[dict] = []
    for key, last_ok, interval in (
        ("anomaly", health.get("anomaly_last_ok"), settings.anomaly_sync_interval),
        ("plan", health.get("plan_last_ok"), settings.plan_sync_interval),
    ):
        if last_ok is None:
            continue  # 从未成功过（刚启动 / 源未配），不误报
        threshold = max(interval * 3, 600)
        if now - last_ok > timedelta(seconds=threshold):
            label = "异常指标" if key == "anomaly" else "计划初稿"
            probs.append({
                "kind": "sync_stall",
                "summary": f"{label}同步疑似中断",
                "detail": f"最近一次成功 {last_ok.strftime('%m-%d %H:%M:%S')}，已超过 {threshold // 60} 分钟没动静",
                "fix": "查 backend/logs/error.log 里 sync 相关报错；确认钉盘/数仓源可访问后重启后端",
            })
    return probs


def _alert_problems(problems: list[dict]) -> None:
    from app.services.alert_service import send_alert

    chunks = []
    for i, p in enumerate(problems, 1):
        chunks.append(f"**{i}. {p['summary']}**\n{p['detail']}\n🧰 {p['fix']}")
    send_alert(
        f"巡检发现 {len(problems)} 类问题",
        detail="\n\n".join(chunks),
        fix="逐条按上面的「怎么修」处理；处理完下一轮巡检会自动核实",
        level="warning",
        key="sweep:problems",
    )


def sweep_once() -> dict:
    """跑一轮巡检，若有问题即告警；供进程内轮询与 Celery beat 复用。"""
    result = run_sweep()
    problems = result.get("problems") or []
    if problems:
        _alert_problems(problems)
    else:
        log.info("[sweep] 巡检通过，未发现静默失效")
    return result


async def poll_sweep_loop(interval: int = 600):
    global _last_run_at
    while True:
        try:
            _last_run_at = datetime.now()
            await asyncio.to_thread(sweep_once)
        except Exception as e:
            log.error("[sweep] 巡检异常: %s", e, exc_info=True)
        await asyncio.sleep(interval)


def start(interval: int | None = None) -> "asyncio.Task | None":
    """启动进程内巡检（本地 dev 由 main lifespan 调用）。"""
    global _task
    if not settings.sweep_enabled:
        return None
    iv = interval or settings.sweep_interval
    if _task is None or _task.done():
        _task = asyncio.create_task(poll_sweep_loop(iv))
        log.info("[sweep] 主动巡检已启动（每 %ss 一轮）", iv)
    return _task


async def stop():
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None