"""工单 CRUD API"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.models import Project, User, WorkOrder, WorkOrderTypeKB, ConfigDefinition, StatusLog, DataPoolItem
from app.schemas.workorder import WorkOrderCreate, WorkOrderListOut, WorkOrderOut, WorkOrderUpdate, StatusLogOut
from app.schemas.pool import BackfillRequest
from app.services.priority_service import normalize_priority
from app.services.roles import resolve_role_user_id

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
        "planned_start_date": wo.planned_start_date, "deadline": wo.deadline,
        "completed_date": wo.completed_date, "oa_id": wo.oa_id,
        "escalation_level": wo.escalation_level, "overdue_days": wo.overdue_days,
        "conclusion": wo.conclusion, "created_at": wo.created_at,
        "project_name": proj.name if proj else None,
        "person_name": person.name if person else None,
        "approver_name": approver.name if approver else None,
        "type_name": wtype.name if wtype else None,
        "region": wo.region,
        # 回填
        "backfill_status": wo.backfill_status,
        "backfill_reason": wo.backfill_reason,
        "backfill_action": wo.backfill_action,
        "backfilled_at": wo.backfilled_at,
        "parent_pool_id": wo.parent_pool_id,
        "triggered_wo_id": wo.triggered_wo_id,
        "triggered_wo_tasks": wo.triggered_wo_tasks,
        # 判断Agent
        "judgment_status": wo.judgment_status,
        "judgment_result": wo.judgment_result,
        "judgment_requested_at": wo.judgment_requested_at,
        "judgment_completed_at": wo.judgment_completed_at,
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
    region: str | None = None,
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
    if region:
        q = q.where(WorkOrder.region == region)
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
    # 优先级按来源定（业务规则 2026-08-20）：
    #   alert(监视告警/异常指标)→P1；plan(年度计划) 由计划自带；meeting/manual 手填，未填兜底 P2
    if body.priority is None:
        body.priority = "P1" if body.source_code == "alert" else "P2"
    else:
        body.priority = normalize_priority(body.priority) or "P2"

    # 未指定审批人时，按工单类型的默认审批人角色解析（后台可配置角色→人名）
    if body.approver_id is None and body.type_id is not None:
        wtype = db.get(WorkOrderTypeKB, body.type_id)
        if wtype:
            body.approver_id = resolve_role_user_id(db, wtype.default_approver_role) or wtype.default_approver_id

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
        region=body.region,
        planned_start_date=body.planned_start_date, deadline=body.deadline,
        created_date=date.today(),
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
        "close": ({"verifying", "judging"}, "closed", "验收通过·闭环"),
        "reject": ({"approving"}, "rejected", "审批驳回"),
        # alert 判断流程专用
        "dispatch_measure": ({"judging"}, "closed", "生成措施工单并闭环"),
        # 重置回待派发（未发起），便于重新测试
        "reset": ({"approving", "dispatched", "executing", "verifying", "overdue", "rejected"}, "pending", "重置为待派发(未发起)"),
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
    if action == "reset":
        # 重置回待派发：清空 OA 单号、闭环日期、逾期与升级痕迹，便于重新发起测试
        wo.oa_id = None
        wo.completed_date = None
        wo.overdue_days = 0
        wo.escalation_level = 0
    if action == "dispatch_measure":
        # 创建措施工单B（支持多个）
        from app.services.pool_service import _create_triggered_wo
        wo.judgment_status = "approved"
        triggered_ids = []

        # 优先使用 tasks 列表，否则用单条
        tasks = wo.triggered_wo_tasks if isinstance(wo.triggered_wo_tasks, list) and wo.triggered_wo_tasks else None
        if tasks:
            for task in tasks:
                if isinstance(task, dict):
                    deadline_val = None
                    dl_str = task.get("deadline", "")
                    if dl_str:
                        try:
                            deadline_val = date.fromisoformat(dl_str)
                        except (ValueError, TypeError):
                            pass
                    tid = _create_triggered_wo(
                        db, wo,
                        task.get("title"),
                        deadline_val,
                        task.get("person_name"),
                        priority=task.get("priority") or wo.priority,
                        task_reason=task.get("reason"),
                        task_action=task.get("action"),
                        type_id=task.get("type_id"),
                    )
                    triggered_ids.append(tid)
        else:
            # 单条模式（兼容旧逻辑）
            tid = _create_triggered_wo(
                db, wo,
                wo.triggered_wo_title,
                wo.triggered_wo_deadline,
                wo.triggered_wo_person_name,
                priority=wo.priority,
            )
            triggered_ids.append(tid)

        codes = []
        for tid in triggered_ids:
            t = db.get(WorkOrder, tid)
            if t:
                codes.append(t.code)
                _launch_oa(t, db)
        # 把生成的工单ID存入triggered_wo_tasks方便前端展示链接
        wo.triggered_wo_tasks = [{"code": c, "id": tid} for c, tid in zip(codes, triggered_ids)]
        note = f"生成{len(codes)}个措施工单并闭环 → {', '.join(codes)}"
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


def _enrich_oa(wo: WorkOrder, db: Session | None = None):
    """尝试发起钉钉 OA 审批，回填真实 OA 实例 ID"""
    try:
        from app.services import dingtalk
        s = db or SessionLocal()
        enriched = _enrich(wo, s)
        instance_id = dingtalk.create_oa_approval(enriched)
        if instance_id and instance_id != wo.oa_id:
            wo.oa_id = instance_id
        if not db:
            s.commit()
            s.close()
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
    """工单回填：alert来源提交后进入「判定中」；其他来源保留原逻辑"""
    from app.services.pool_service import backfill_work_order as _backfill
    try:
        result = _backfill(
            db, wo_id,
            reason=body.reason, action=body.action,
            trigger_new_wo=body.trigger_new_wo,
            new_wo_title=body.new_wo_title,
            new_wo_deadline=body.new_wo_deadline,
            new_wo_person_name=body.new_wo_person_name,
            accept_judgment=body.accept_judgment,
            override_judgment=body.override_judgment,
        )

        # alert 来源：回填后进入「已回填」，同时把回填措施写入工单的 action 字段
        wo = db.get(WorkOrder, wo_id)
        if wo and wo.source_code == "alert" and wo.status == "pending":
            wo.status = "judging"
            wo.judgment_status = "judging"
            # 把回填内容同步到工单详情：原因→reason，措施→action
            if wo.backfill_reason:
                wo.reason = wo.backfill_reason
            if wo.backfill_action:
                wo.action = wo.backfill_action
            db.add(StatusLog(work_order_id=wo.id, from_status="pending",
                           to_status="judging", note="回填完成·进入已回填"))
            db.commit()
            db.refresh(wo)

        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{wo_id}/backfill")
def get_backfill(wo_id: int, db: Session = Depends(get_db)):
    """查看回填记录（含判断Agent结果）"""
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
        "reason": wo.backfill_reason,
        "action": wo.backfill_action,
        "backfilled_at": wo.backfilled_at.isoformat() if wo.backfilled_at else None,
        "triggered_wo_id": wo.triggered_wo_id,
        "triggered_wo_code": triggered_code,
        "triggered_wo_tasks": wo.triggered_wo_tasks,
        "parent_pool_id": wo.parent_pool_id,
        # 判断Agent
        "verdict": wo.judgment_status,
        "judgment_reasoning": wo.judgment_result.get("reasoning") if wo.judgment_result else None,
        "judgment_suggestions": wo.judgment_result.get("suggestions") if wo.judgment_result else None,
        "judgment_confidence": wo.judgment_result.get("confidence") if wo.judgment_result else None,
    }


# ── 判断Agent 导出/导入（桥接方案，Agent服务上线前的离线协作） ─────

@router.get("/{wo_id}/export-judgment")
def export_judgment(wo_id: int, db: Session = Depends(get_db)):
    """导出工单数据为判断Agent输入格式（JSON文件下载）

    生成符合「指标异常处置SOP技能」输入契约的JSON文件。
    PMO下载后交给技术团队，由Agent完成归因+措施制定。
    """
    from datetime import datetime, timezone

    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    if wo.source_code != "alert":
        raise HTTPException(400, "仅监视告警来源的工单支持导出判断")

    # 获取项目名
    proj = db.get(Project, wo.project_id) if wo.project_id else None

    # 获取关联数据池记录
    pool = db.query(DataPoolItem).filter(DataPoolItem.id == wo.parent_pool_id).first() if wo.parent_pool_id else None

    export_data = {
        "export_version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "wo-closed-loop",
        "work_order": {
            "code": wo.code,
            "title": wo.title,
            "station_name": proj.name if proj else None,
            "region": wo.region,
            "priority": wo.priority,
            "created_date": str(wo.created_date) if wo.created_date else None,
        },
        "anomaly": {
            "module": "reliability",
            "metric_type": pool.metric_type if pool else None,
            "metric_value": pool.metric_value if pool else None,
            "threshold": pool.threshold if pool else None,
            "deviation_pct": pool.deviation_pct if pool else None,
            "period": str(wo.created_date)[:7] if wo.created_date else None,
            "description": pool.description if pool else (wo.reason or ""),
            # 以下字段供Agent补充，若数据池有原始数据则填入
            "event_category": None,
            "fault_duration_h": None,
            "fault_frequency": None,
            "lost_energy_kwh": None,
            "diagnosis_hours": None,
            "cj2_hours": None,
            "spare_parts_wait_hours": None,
            "repeated_same_component": None,
            "external_type": None,
            "major_component_name": None,
            "note": "event_category等EAM字段请技术团队根据实际停机日志补充。若无法获取，Agent请根据backfill.reason和backfill.action文本推断。",
        },
        "backfill": {
            "reason": wo.backfill_reason,
            "action": wo.backfill_action,
            "backfilled_at": wo.backfilled_at.isoformat() if wo.backfilled_at else None,
        },
        "proposed_work_order": {
            "title": wo.triggered_wo_title,
            "deadline": str(wo.triggered_wo_deadline) if wo.triggered_wo_deadline else None,
            "person_name": wo.triggered_wo_person_name,
            "priority": wo.priority,
        },
        "raw_data": pool.raw_data if pool else None,
    }

    from fastapi.responses import JSONResponse
    filename = f"judgment_export_{wo.code}.json"
    return JSONResponse(
        content=export_data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{wo_id}/import-judgment")
def import_judgment(wo_id: int, body: dict, db: Session = Depends(get_db)):
    """导入判断Agent返回的结果JSON，自动回填原因+措施

    接收Agent输出的归因分析结果，将原因和措施写入工单的回填字段。
    PMO审核后，勾选"生成新工单"提交即可创建措施工单。
    """
    from datetime import datetime, timezone

    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")

    # 提取 Agent 输出
    reasoning = body.get("reasoning", "")
    analysis = body.get("analysis", {})
    measures = body.get("measures", [])
    tasks = body.get("tasks", [])
    confidence = body.get("confidence")

    # 构建回填原因：归因分析
    backfill_reason = reasoning
    if analysis and isinstance(analysis, dict):
        root_causes = analysis.get("root_causes", [])
        if root_causes:
            lines = [reasoning] if reasoning else []
            for rc in root_causes:
                if isinstance(rc, dict):
                    prelim = rc.get("preliminary_cause", "")
                    root = rc.get("root_cause", "")
                    evidence = rc.get("evidence", "")
                    lines.append(f"• {prelim} → {root}" + (f"（{evidence}）" if evidence else ""))
            backfill_reason = "\n".join(lines)

    # 构建回填措施：从 measures 和 tasks 拼
    action_parts = []
    if isinstance(measures, list):
        for m in measures:
            if isinstance(m, dict):
                action_parts.append(f"• {m.get('measure', str(m))}")
    if isinstance(tasks, list):
        for t in tasks:
            if isinstance(t, dict):
                action_parts.append(f"→ 工单：{t.get('title', str(t))} | 责任人：{t.get('responsible', '?')} | 截止：{t.get('deadline', '?')}")

    backfill_action = "\n".join(action_parts)

    # 自动回填
    wo.backfill_status = "filled"
    wo.backfill_reason = backfill_reason
    wo.backfill_action = backfill_action
    wo.backfilled_at = datetime.now(timezone.utc)
    # 同步到工单详情：原因→reason，措施→action
    if backfill_reason:
        wo.reason = backfill_reason
    if backfill_action:
        wo.action = backfill_action

    # 保存判断结果
    wo.judgment_status = "imported"
    wo.judgment_result = {
        "verdict": body.get("verdict", "approved_suggested"),
        "confidence": confidence,
        "reasoning": reasoning,
        "analysis": analysis,
        "measures": measures,
        "tasks": tasks,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    wo.judgment_requested_at = wo.judgment_requested_at or datetime.now(timezone.utc)
    wo.judgment_completed_at = datetime.now(timezone.utc)

    # 如果 Agent 给了 tasks，自动填入建议的新工单参数
    if isinstance(tasks, list) and len(tasks) > 0:
        t0 = tasks[0] if isinstance(tasks[0], dict) else {}
        wo.triggered_wo_title = t0.get("title", "") if isinstance(t0, dict) else str(t0)
        wo.triggered_wo_person_name = t0.get("responsible", "") if isinstance(t0, dict) else ""
        deadline_str = t0.get("deadline", "") if isinstance(t0, dict) else ""
        if deadline_str:
            try:
                wo.triggered_wo_deadline = date.fromisoformat(deadline_str)
            except (ValueError, TypeError):
                pass

    db.add(StatusLog(work_order_id=wo.id, from_status=wo.status,
                    to_status=wo.status, note="导入Agent判断结果·自动回填"))

    # 回传数据池
    if wo.parent_pool_id:
        pool = db.get(DataPoolItem, wo.parent_pool_id)
        if pool:
            pool.backfill_reason = backfill_reason
            pool.backfill_action = backfill_action
            pool.backfilled_at = wo.backfilled_at

    db.commit()
    db.refresh(wo)

    return {
        "work_order_id": wo.id,
        "backfill_reason": backfill_reason,
        "backfill_action": backfill_action,
        "triggered_wo_title": wo.triggered_wo_title,
        "triggered_wo_deadline": str(wo.triggered_wo_deadline) if wo.triggered_wo_deadline else None,
        "triggered_wo_person_name": wo.triggered_wo_person_name,
        "judgment_status": wo.judgment_status,
        "confidence": confidence,
        "reasoning": reasoning,
    }


# ── 批量跟踪仪表盘 ──────────────────────────────────

@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    """批量工单跟踪仪表盘：状态分布 + 即将到期 + 已逾期"""
    from datetime import date, timedelta

    today = date.today()
    tomorrow = today + timedelta(days=1)

    # 所有非闭环工单
    active = (
        db.query(WorkOrder)
        .filter(~WorkOrder.status.in_(["closed", "rejected"]))
        .all()
    )

    # 状态分布
    status_counts = {}
    for wo in active:
        status_counts[wo.status] = status_counts.get(wo.status, 0) + 1

    # 即将到期（24h内）
    due_soon = [
        {
            "id": wo.id, "code": wo.code, "title": wo.title,
            "deadline": str(wo.deadline) if wo.deadline else None,
            "status": wo.status, "priority": wo.priority,
        }
        for wo in active
        if wo.deadline and 0 <= (wo.deadline - today).days <= 1
    ]

    # 已逾期
    overdue = [
        {
            "id": wo.id, "code": wo.code, "title": wo.title,
            "deadline": str(wo.deadline) if wo.deadline else None,
            "overdue_days": wo.overdue_days,
            "status": wo.status, "priority": wo.priority,
            "escalation_level": wo.escalation_level,
        }
        for wo in active
        if wo.status == "overdue"
    ]

    # 按优先级统计
    priority_counts = {}
    for wo in active:
        priority_counts[wo.priority] = priority_counts.get(wo.priority, 0) + 1

    return {
        "total_active": len(active),
        "status_distribution": status_counts,
        "priority_distribution": priority_counts,
        "due_soon": due_soon,
        "due_soon_count": len(due_soon),
        "overdue": overdue,
        "overdue_count": len(overdue),
        "scanned_at": today.isoformat(),
    }


@router.get("/dashboard/timeline")
def dashboard_timeline(
    project_id: int | None = None,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """工单时间线：按截止日期分布，用于批量查看全年工单"""
    from datetime import date

    today = date.today()
    start = today - timedelta(days=30)
    end = today + timedelta(days=days)

    q = (
        db.query(WorkOrder)
        .filter(WorkOrder.deadline.between(start, end))
        .order_by(WorkOrder.deadline.asc())
    )
    if project_id:
        q = q.filter(WorkOrder.project_id == project_id)

    rows = q.all()
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "total": len(rows),
        "items": [
            {
                "id": wo.id, "code": wo.code, "title": wo.title,
                "deadline": str(wo.deadline) if wo.deadline else None,
                "status": wo.status, "priority": wo.priority,
                "oa_id": wo.oa_id,
            }
            for wo in rows
        ],
    }


# 保持 WorkOrderUpdate 引用以兼容旧代码路径
