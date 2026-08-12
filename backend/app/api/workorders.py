"""工单 CRUD API"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, User, WorkOrder, WorkOrderTypeKB, ConfigDefinition, StatusLog
from app.schemas.workorder import WorkOrderCreate, WorkOrderListOut, WorkOrderOut, WorkOrderUpdate, StatusLogOut
from app.schemas.pool import BackfillRequest
from app.services.priority_service import match_priority

router = APIRouter(prefix="/work-orders", tags=["work-orders"])


def _enrich(wo: WorkOrder, db: Session) -> WorkOrderOut:
    """填充关联名称"""
    proj = db.get(Project, wo.project_id) if wo.project_id else None
    person = db.get(User, wo.person_id) if wo.person_id else None
    approver = db.get(User, wo.approver_id) if wo.approver_id else None
    wtype = db.get(WorkOrderTypeKB, wo.type_id) if wo.type_id else None
    d = {
        "id": wo.id, "code": wo.code, "title": wo.title, "reason": wo.reason,
        "action": wo.action, "project_id": wo.project_id, "person_id": wo.person_id,
        "approver_id": wo.approver_id, "type_id": wo.type_id, "source_code": wo.source_code,
        "priority": wo.priority, "status": wo.status, "created_date": wo.created_date,
        "deadline": wo.deadline, "completed_date": wo.completed_date, "oa_id": wo.oa_id,
        "escalation_level": wo.escalation_level, "overdue_days": wo.overdue_days,
        "conclusion": wo.conclusion, "created_at": wo.created_at,
        "project_name": proj.name if proj else None,
        "person_name": person.name if person else None,
        "approver_name": approver.name if approver else None,
        "type_name": wtype.name if wtype else None,
    }
    return WorkOrderOut(**d)


def _next_code(db: Session) -> str:
    year = date.today().year
    prefix = f"RW-{year}-"
    cnt = db.query(WorkOrder).filter(WorkOrder.code.like(f"{prefix}%")).count()
    return f"{prefix}{cnt + 1:04d}"


@router.get("", response_model=WorkOrderListOut)
def list_work_orders(
    project_id: int | None = None,
    source_code: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    person_name: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = select(WorkOrder).order_by(WorkOrder.created_date.desc(), WorkOrder.id.desc())
    if project_id:
        q = q.where(WorkOrder.project_id == project_id)
    if source_code:
        q = q.where(WorkOrder.source_code == source_code)
    if status:
        q = q.where(WorkOrder.status == status)
    if priority:
        q = q.where(WorkOrder.priority == priority)
    if person_name:
        q = q.join(User, WorkOrder.person_id == User.id).where(User.name.ilike(f"%{person_name}%"))
    if search:
        q = q.where(WorkOrder.title.ilike(f"%{search}%"))

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    items = [_enrich(r, db) for r in rows]
    return WorkOrderListOut(items=items, total=total or 0, page=page, page_size=page_size)


@router.get("/closed/list", response_model=WorkOrderListOut)
def list_closed(
    project_id: int | None = None,
    source_code: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """已闭环工单归档列表（含耗时、是否逾期）"""
    q = select(WorkOrder).where(WorkOrder.status == "closed").order_by(WorkOrder.completed_date.desc())
    if project_id:
        q = q.where(WorkOrder.project_id == project_id)
    if source_code:
        q = q.where(WorkOrder.source_code == source_code)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    items = []
    for r in rows:
        e = _enrich(r, db)
        dur = None
        if r.created_date and r.completed_date:
            dur = (r.completed_date - r.created_date).days
        e.duration_days = dur
        e.is_overdue = (r.overdue_days or 0) > 0
        items.append(e)
    return WorkOrderListOut(items=items, total=total or 0, page=page, page_size=page_size)


@router.get("/{wo_id}", response_model=WorkOrderOut)
def get_work_order(wo_id: int, db: Session = Depends(get_db)):
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    return _enrich(wo, db)


@router.post("", response_model=WorkOrderOut, status_code=201)
def create_work_order(body: WorkOrderCreate, db: Session = Depends(get_db)):
    # 自动优先级（若未指定或为默认 P2 但文本含关键字）
    if body.priority == "P2" and not body.priority:
        body.priority = match_priority(db, f"{body.title} {body.reason or ''}", body.source_code)

    # 若未指定截止日期，按 SLA 默认
    if not body.deadline:
        from app.models import SLADefinition
        sla = db.query(SLADefinition).filter_by(priority=body.priority).first()
        days = sla.deadline_days if sla else 7
        body.deadline = date.today() + timedelta(days=days)

    wo = WorkOrder(
        code=_next_code(db),
        title=body.title, reason=body.reason, action=body.action,
        project_id=body.project_id, person_id=body.person_id, approver_id=body.approver_id,
        type_id=body.type_id, source_code=body.source_code, priority=body.priority,
        deadline=body.deadline, created_date=date.today(),
        # 建单即发起钉钉审批 → 初始 approving
        status="approving",
    )
    db.add(wo)
    db.flush()
    db.add(StatusLog(work_order_id=wo.id, from_status=None, to_status="approving", note="创建工单·发起钉钉审批"))
    db.commit()
    db.refresh(wo)
    # 同步发起钉钉 OA 审批（多节点流：审批人→执行人→审批人确认）
    _launch_oa(wo, db)
    return _enrich(wo, db)


def _launch_oa(wo: WorkOrder, db: Session):
    """建单后发起钉钉 OA 审批，回填审批实例 ID。无凭证时占位。"""
    try:
        from app.services import dingtalk
        enriched = _enrich(wo, db)
        instance_id = dingtalk.create_oa_approval(enriched)
        if instance_id:
            wo.oa_id = instance_id
            db.commit()
    except Exception as e:
        print(f"[workorder] 发起钉钉审批跳过: {e}")


@router.patch("/{wo_id}", response_model=WorkOrderOut)
def update_work_order(wo_id: int, body: WorkOrderUpdate, db: Session = Depends(get_db)):
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    data = body.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    for k, v in data.items():
        setattr(wo, k, v)
    if new_status and new_status != wo.status:
        db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=new_status))
        wo.status = new_status
    db.commit()
    db.refresh(wo)
    return _enrich(wo, db)


@router.get("/{wo_id}/attachments")
def get_attachments(wo_id: int, db: Session = Depends(get_db)):
    """工单附件列表（含钉钉同步的执行附件）"""
    from app.models import Attachment
    rows = db.query(Attachment).filter_by(work_order_id=wo_id).all()
    return [{"id": a.id, "filename": a.filename, "oss_key": a.oss_key, "size": a.size,
             "created_at": a.created_at.isoformat() if a.created_at else None} for a in rows]


@router.get("/{wo_id}/status-logs", response_model=list[StatusLogOut])
def get_status_logs(wo_id: int, db: Session = Depends(get_db)):
    """工单状态流转日志（时间线用）"""
    logs = (
        db.query(StatusLog)
        .filter(StatusLog.work_order_id == wo_id)
        .order_by(StatusLog.created_at.desc(), StatusLog.id.desc())
        .all()
    )
    out = []
    for lg in logs:
        op = db.get(User, lg.operator_id) if lg.operator_id else None
        out.append(StatusLogOut(
            id=lg.id, from_status=lg.from_status, to_status=lg.to_status,
            operator_name=op.name if op else None, note=lg.note,
            created_at=lg.created_at,
        ))
    return out


@router.post("/{wo_id}/transition", response_model=WorkOrderOut)
def transition_work_order(wo_id: int, action: str, db: Session = Depends(get_db)):
    """快捷状态流转：dispatch|start_exec|submit_evidence|close|reject"""
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    from datetime import date as _date
    # action: (允许的来源状态集合, 目标状态, 备注)
    transitions = {
        "dispatch": ({"pending", "approving"}, "dispatched", "派发·发起OA审批"),
        "start_exec": ({"dispatched"}, "executing", "开始执行"),
        "submit_evidence": ({"executing"}, "verifying", "提交佐证·待验收"),
        "close": ({"verifying"}, "closed", "验收通过·闭环"),
        "reject": ({"approving"}, "rejected", "审批驳回"),
    }
    if action not in transitions:
        raise HTTPException(400, f"未知操作: {action}")
    allowed_from, to, note = transitions[action]
    if wo.status not in allowed_from:
        raise HTTPException(409, f"当前状态 {wo.status} 不允许此操作（需 {list(allowed_from)}）")
    if action == "dispatch" and not wo.oa_id:
        # 本地占位 OA 单号；若配置了钉钉则尝试发起真实 OA 审批
        wo.oa_id = "OA-" + _date.today().strftime("%Y%m%d") + "-" + str(wo.id).zfill(3)
        _enrich_oa(wo)
    db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=to, note=note))
    wo.status = to
    if to == "closed" and not wo.completed_date:
        wo.completed_date = _date.today()
        if not wo.conclusion:
            wo.conclusion = "验收通过"
    if to == "closed" and wo.deadline and wo.completed_date and wo.completed_date > wo.deadline:
        wo.overdue_days = (wo.completed_date - wo.deadline).days
    db.commit()
    db.refresh(wo)
    # 异步触发通知（开发环境 Celery eager 同步执行）
    _trigger_notify(wo.id, action, to)
    return _enrich(wo, db)


def _enrich_oa(wo: WorkOrder):
    """尝试发起钉钉 OA 审批（未配置 key 时静默跳过）"""
    try:
        from app.services import dingtalk
        from app.core.database import SessionLocal
        db = SessionLocal()
        enriched = _enrich(wo, db)
        db.close()
        dingtalk.create_oa_approval(enriched)
    except Exception as e:
        print(f"[workorder] OA 发起跳过: {e}")


def _trigger_notify(wo_id: int, action: str, to_status: str):
    """流转后触发通知"""
    try:
        from app.tasks import send_notification_task
        event_map = {
            "dispatch": "dispatch",
            "submit_evidence": "sla_warn",  # 待验收提醒审批人
            "close": "dispatch",  # 闭环通知（复用 dispatch 模板，实际可单独配）
        }
        event = event_map.get(action)
        if event:
            send_notification_task.delay(wo_id, event)
    except Exception as e:
        print(f"[workorder] 通知触发跳过: {e}")


@router.post("/{wo_id}/notify")
def notify_work_order(wo_id: int, event: str, db: Session = Depends(get_db)):
    """手动触发工单通知（钉钉集成页测试用）"""
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    from app.services.notification_service import send_notification
    return send_notification(wo_id, event)


# ── 回填（Phase 3.5）──────────────────────────────────

@router.post("/{wo_id}/backfill")
def backfill_work_order(
    wo_id: int,
    body: BackfillRequest,
    db: Session = Depends(get_db),
):
    """工单回填：责任人填写原因+措施，可选触发新工单"""
    from app.services.pool_service import backfill_work_order as _backfill
    try:
        result = _backfill(
            db, wo_id,
            reason=body.reason, action=body.action,
            trigger_new_wo=body.trigger_new_wo,
            new_wo_title=body.new_wo_title,
            new_wo_deadline=body.new_wo_deadline,
            new_wo_person_name=body.new_wo_person_name,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{wo_id}/backfill")
def get_backfill(wo_id: int, db: Session = Depends(get_db)):
    """查看回填记录"""
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    triggered_code = None
    if wo.triggered_wo_id:
        triggered = db.get(WorkOrder, wo.triggered_wo_id)
        triggered_code = triggered.code if triggered else None
    return {
        "work_order_id": wo.id,
        "backfill_status": wo.backfill_status,
        "backfill_reason": wo.backfill_reason,
        "backfill_action": wo.backfill_action,
        "backfilled_at": wo.backfilled_at.isoformat() if wo.backfilled_at else None,
        "triggered_wo_id": wo.triggered_wo_id,
        "triggered_wo_code": triggered_code,
        "parent_pool_id": wo.parent_pool_id,
    }


# 保持 WorkOrderUpdate 引用以兼容旧代码路径
