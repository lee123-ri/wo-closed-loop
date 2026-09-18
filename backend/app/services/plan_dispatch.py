"""年度运营计划工单按月自动派发 OA。

计划工单导入后落 `scheduled`（排期），不立即发起 OA（手动流与钉钉审批流一一对应）。
每月 1 日 09:00（本地时间，与 celery timezone=Asia/Shanghai 一致）由 Celery beat 触发：
挑选「计划开始日落在当月」且「OA 发起必填完整」的 source_code=plan & status=scheduled 工单，
统一发起钉钉 OA，成功后置 `approving`。

幂等：只处理 oa_id 为空 / 本地占位 "OA-" 的工单；重复执行不会重发。
"""
from datetime import date, datetime

from app.core.database import SessionLocal
from app.models import StatusLog, WorkOrder


def _month_bounds(now: datetime | None = None) -> tuple[date, date]:
    """当月闭区间转 [月初, 下月初)。本地时间，与项目其它定时任务一致。"""
    now = now or datetime.now()
    first = date(now.year, now.month, 1)
    if now.month == 12:
        nxt = date(now.year + 1, 1, 1)
    else:
        nxt = date(now.year, now.month + 1, 1)
    return first, nxt


def dispatch_monthly_plans(now: datetime | None = None, db=None) -> dict:
    """按月自动派发：当月计划开始日 + 完整的 plan 工单 → 发起 OA → approving。

    返回 {"dispatched", "skipped_incomplete", "failed"} 供日志与（可选）管理 API 查看。
    db：可选传入外部会话（测试注入用）；默认 None 时函数自开自关 SessionLocal。
    """
    from app.services.dingtalk import create_oa_approval, plan_completeness_missing

    first, nxt = _month_bounds(now)
    own_db = db is None
    if own_db:
        db = SessionLocal()
    from app.services.maintenance import is_paused
    if is_paused(db):
        if own_db:
            db.close()
        return {"paused": True, "dispatched": 0, "skipped_incomplete": 0, "failed": 0}
    dispatched = skipped_incomplete = failed = 0
    try:
        wos = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.source_code == "plan",
                WorkOrder.status == "scheduled",
                WorkOrder.planned_start_date >= first,
                WorkOrder.planned_start_date < nxt,
            )
            .all()
        )
        for wo in wos:
            # 幂等：已有真实 OA 实例（非占位 "OA-"）的不重发
            if wo.oa_id and not str(wo.oa_id).startswith("OA-"):
                continue
            # 二次校验：导入门禁挡过一轮，这里是防倾斜兜底——缺项绝不带空字段发起 OA
            missing = plan_completeness_missing(wo)
            if missing:
                print(f"[plan-dispatch] 工单 {wo.code} 缺必填，跳过：{'/'.join(missing)}", flush=True)
                skipped_incomplete += 1
                continue
            instance_id = create_oa_approval(wo)
            if not instance_id:
                print(f"[plan-dispatch] 工单 {wo.code} 发起 OA 失败，保持 scheduled", flush=True)
                failed += 1
                continue
            wo.oa_id = instance_id
            wo.status = "approving"
            db.add(StatusLog(work_order_id=wo.id, from_status="scheduled", to_status="approving",
                             note="按月自动派发·发起钉钉OA"))
            dispatched += 1
        db.commit()
    finally:
        if own_db:
            db.close()
    result = {"dispatched": dispatched, "skipped_incomplete": skipped_incomplete, "failed": failed}
    if dispatched or skipped_incomplete or failed:
        print(f"[plan-dispatch] 当月计划自动派发：{result}", flush=True)
    return result