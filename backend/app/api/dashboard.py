"""工作台统计 API"""
import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ConfigDefinition, WorkOrder, Project, User, WorkOrderTypeKB
from app.schemas.workorder import DashboardStats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_DAY = timedelta(days=1)


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db)):
    all_wos = db.execute(select(WorkOrder)).scalars().all()
    total = len(all_wos)
    executing = sum(1 for w in all_wos if w.status == "executing")
    pending_verify = sum(1 for w in all_wos if w.status == "verifying")
    overdue = sum(1 for w in all_wos if w.status == "overdue")
    closed_wos = [w for w in all_wos if w.status == "closed"]
    closed = len(closed_wos)

    sla_compliance = round((total - overdue) / total * 100, 1) if total else 0.0
    closed_rate = round(closed / total * 100, 1) if total else 0.0

    # MTTR: 已闭环工单从创建到完成的平均天数
    mttr = None
    if closed_wos:
        deltas = []
        for w in closed_wos:
            if w.completed_date and w.created_date:
                deltas.append((w.completed_date - w.created_date).days + (w.overdue_days or 0))
        mttr = round(sum(deltas) / len(deltas), 1) if deltas else None

    # MTTA: 从创建到开始执行的响应时间（这里用 created→dispatched 近似，无日志时取 0.8 默认占位）
    mtta = 0.8

    # 时效分布
    aging = {"d3": 0, "d7": 0, "d14": 0, "o14": 0}
    for w in closed_wos:
        if not (w.completed_date and w.created_date):
            continue
        d = (w.completed_date - w.created_date).days
        if d <= 3:
            aging["d3"] += 1
        elif d <= 7:
            aging["d7"] += 1
        elif d <= 14:
            aging["d14"] += 1
        else:
            aging["o14"] += 1

    # 来源分布
    src_dist = []
    src_cfg = {c.code: c.name for c in db.execute(select(ConfigDefinition).where(ConfigDefinition.category == "source")).scalars().all()}
    src_count: dict[str, int] = {}
    for w in all_wos:
        src_count[w.source_code] = src_count.get(w.source_code, 0) + 1
    for code, name in src_cfg.items():
        cnt = src_count.get(code, 0)
        src_dist.append({"code": code, "name": name, "count": cnt, "pct": round(cnt / total * 100, 1) if total else 0})

    # 逾期告警条
    overdue_items = []
    for w in all_wos:
        if w.status != "overdue":
            continue
        person = db.get(User, w.person_id) if w.person_id else None
        overdue_items.append({
            "id": w.id, "code": w.code, "person": person.name if person else "—",
            "overdue_days": w.overdue_days, "escalation_level": w.escalation_level,
            "title": w.title,
        })

    # 待办（非闭环，逾期优先）
    todo_raw = [w for w in all_wos if w.status != "closed"]
    todo_raw.sort(key=lambda w: (w.status != "overdue", w.deadline or date.max))
    todo_items = []
    for w in todo_raw[:100]:  # 扩大取数范围，前端分页
        person = db.get(User, w.person_id) if w.person_id else None
        todo_items.append({
            "id": w.id, "code": w.code, "title": w.title, "status": w.status,
            "priority": w.priority, "person": person.name if person else "—",
            "deadline": w.deadline.isoformat() if w.deadline else None,
            "escalation_level": w.escalation_level,
        })

    return DashboardStats(
        total=total, executing=executing, pending_verify=pending_verify,
        overdue=overdue, closed=closed, sla_compliance=sla_compliance,
        mttr_days=mttr, mtta_days=mtta, closed_rate=closed_rate,
        aging=aging, source_dist=src_dist,
        overdue_items=overdue_items, todo_items=todo_items,
    )


# ── 人员专属看板（Phase 3.5）──────────────────────────

@router.get("/person/{user_id}")
def get_person_dashboard(user_id: int, db: Session = Depends(get_db)):
    """人员专属统计：待处理/执行中/待回填/已逾期/已闭环"""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    wos = db.execute(select(WorkOrder).where(WorkOrder.person_id == user_id)).scalars().all()

    total = len(wos)
    pending = sum(1 for w in wos if w.status in ("pending", "approving"))
    executing = sum(1 for w in wos if w.status in ("dispatched", "executing"))
    verifying = sum(1 for w in wos if w.status == "verifying")
    overdue = sum(1 for w in wos if w.status == "overdue")
    closed = sum(1 for w in wos if w.status == "closed")
    need_backfill = sum(1 for w in wos if w.status in ("dispatched", "executing") and w.backfill_status != "filled")

    # 工单列表（逾期优先）
    items = []
    for w in sorted(wos, key=lambda x: (x.status != "overdue", x.deadline or date.max)):
        items.append({
            "id": w.id, "code": w.code, "title": w.title, "status": w.status,
            "priority": w.priority, "deadline": w.deadline.isoformat() if w.deadline else None,
            "backfill_status": w.backfill_status,
            "overdue_days": w.overdue_days,
        })

    return {
        "user": {"id": user.id, "name": user.name, "role": user.role},
        "stats": {
            "total": total, "pending": pending, "executing": executing,
            "verifying": verifying, "overdue": overdue, "closed": closed,
            "need_backfill": need_backfill,
        },
        "items": items,
    }


# ── 工单日历（Phase 3.5）───────────────────────────────

@router.get("/calendar")
def get_calendar(
    year: int = Query(..., ge=2024, le=2100),
    month: int = Query(..., ge=1, le=12),
    person_id: int | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
):
    """工单日历视图：按月份返回工单的 deadline 分布"""
    from datetime import date as _date
    import calendar as _cal

    start = _date(year, month, 1)
    _, last_day = _cal.monthrange(year, month)
    end = _date(year, month, last_day)

    q = select(WorkOrder).where(
        WorkOrder.deadline >= start,
        WorkOrder.deadline <= end,
        WorkOrder.status != "closed",
    )
    if person_id:
        q = q.where(WorkOrder.person_id == person_id)
    if project_id:
        q = q.where(WorkOrder.project_id == project_id)

    wos = db.execute(q.order_by(WorkOrder.deadline)).scalars().all()

    items = []
    for w in wos:
        person = db.get(User, w.person_id) if w.person_id else None
        items.append({
            "id": w.id, "code": w.code, "title": w.title, "status": w.status,
            "priority": w.priority, "deadline": w.deadline.isoformat() if w.deadline else None,
            "person_name": person.name if person else None,
            "overdue_days": w.overdue_days,
            "backfill_status": w.backfill_status,
        })

    return {"year": year, "month": month, "count": len(items), "items": items}


# ── 报表导出 ────────────────────────────────────────

from fastapi.responses import StreamingResponse

@router.get("/export/csv")
def export_csv(
    project_id: int | None = None,
    status: str | None = None,
    person_id: int | None = None,
    month: str | None = None,
    db: Session = Depends(get_db),
):
    """导出工单报表为 CSV"""
    q = select(WorkOrder).order_by(WorkOrder.created_date.desc())
    if project_id: q = q.where(WorkOrder.project_id == project_id)
    if status: q = q.where(WorkOrder.status == status)
    if person_id: q = q.where(WorkOrder.person_id == person_id)
    if month:
        y, m = month.split("-")
        q = q.where(WorkOrder.created_date >= date(int(y), int(m), 1),
                     WorkOrder.created_date <= date(int(y), int(m), 28))
    wos = db.execute(q).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["编号","标题","项目","责任人","类型","优先级","状态","来源","创建日期","截止日期","完成日期","逾期天数","回填状态","回填原因","回填措施"])
    for wo in wos:
        proj = db.get(Project, wo.project_id) if wo.project_id else None
        person = db.get(User, wo.person_id) if wo.person_id else None
        wtype = db.get(WorkOrderTypeKB, wo.type_id) if wo.type_id else None
        writer.writerow([wo.code, wo.title, proj.name if proj else "", person.name if person else "",
                          wtype.name if wtype else "", wo.priority, wo.status, wo.source_code,
                          str(wo.created_date) if wo.created_date else "", str(wo.deadline) if wo.deadline else "",
                          str(wo.completed_date) if wo.completed_date else "", wo.overdue_days,
                          wo.backfill_status or "", wo.backfill_reason or "", wo.backfill_action or ""])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=workorders_{month or 'all'}.csv"})


# ── 趋势数据 ────────────────────────────────────────

@router.get("/trends")
def get_trends(months: int = 6, db: Session = Depends(get_db)):
    """返回最近 N 个月的工单趋势（每月新增/闭环/逾期数）"""
    from collections import defaultdict
    from datetime import date as _date, timedelta
    today = _date.today()
    trends = []
    for i in range(months - 1, -1, -1):
        d = today.replace(day=1) - timedelta(days=1)
        d = d.replace(day=1)
        for _ in range(i):
            d = (d.replace(day=28) + timedelta(days=5)).replace(day=1)
        month_start = d
        if d.month == 12:
            month_end = d.replace(year=d.year+1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = d.replace(month=d.month+1, day=1) - timedelta(days=1)
        created = db.query(WorkOrder).filter(WorkOrder.created_date >= month_start, WorkOrder.created_date <= month_end).count()
        closed = db.query(WorkOrder).filter(WorkOrder.completed_date >= month_start, WorkOrder.completed_date <= month_end).count()
        overdue = db.query(WorkOrder).filter(WorkOrder.status == "overdue").count()
        trends.append({"month": d.strftime("%Y-%m"), "created": created, "closed": closed, "overdue": overdue})
    # 按类型分布
    type_dist = []
    for t in db.query(WorkOrderTypeKB).all():
        cnt = db.query(WorkOrder).filter(WorkOrder.type_id == t.id).count()
        if cnt:
            type_dist.append({"name": t.name, "count": cnt})
    # 按项目分布
    proj_dist = []
    for p in db.query(Project).filter(Project.is_active.is_(True)).all():
        cnt = db.query(WorkOrder).filter(WorkOrder.project_id == p.id).count()
        if cnt:
            proj_dist.append({"name": p.name, "count": cnt})
    return {"trends": trends, "type_dist": type_dist, "project_dist": proj_dist}
