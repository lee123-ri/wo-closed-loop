"""工单 CRUD API"""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.logging import get_logger
from app.api.auth import require_admin, require_auth
from app.models import (
    AnomalyOccurrence, Attachment, DataPoolItem, EscalationLog, JudgmentDegradationLog,
    NotificationLog, Project, StatusLog, User, WorkOrder, WorkOrderMeasureLink, WorkOrderTypeKB,
    ConfigDefinition,
)
from app.schemas.workorder import (
    WorkOrderBasicUpdate, WorkOrderCreate, WorkOrderListOut, WorkOrderOut, WorkOrderUpdate, StatusLogOut,
)
from app.schemas.pool import BackfillRequest
from app.services.priority_service import normalize_priority
from app.services.roles import resolve_role_user_id
from app.services.scope import apply_scope_to_query

router = APIRouter(prefix="/work-orders", tags=["work-orders"])
log = get_logger(__name__)


def _actor_id(user) -> int | None:
    """路由注入时取操作人 id；测试直接调函数（传不进 Depends）时返回 None。"""
    return user.id if isinstance(user, User) else None


def _enrich(wo: WorkOrder, db: Session) -> WorkOrderOut:
    """填充关联名称"""
    proj = db.get(Project, wo.project_id) if wo.project_id else None
    person = db.get(User, wo.person_id) if wo.person_id else None
    approver = db.get(User, wo.approver_id) if wo.approver_id else None
    wtype = db.get(WorkOrderTypeKB, wo.type_id) if wo.type_id else None
    d = {
        "id": wo.id, "code": wo.code, "client_request_id": wo.client_request_id,
        "title": wo.title, "reason": wo.reason,
        "action": wo.action, "project_id": wo.project_id, "person_id": wo.person_id,
        "approver_id": wo.approver_id, "type_id": wo.type_id, "source_code": wo.source_code,
        "metric_type": wo.metric_type, "alert_phase": wo.alert_phase,
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
    # alert 主单补充措施进度（2/11）+ 发生记录
    if wo.source_code == "alert":
        from app.services.pool_service import measure_progress
        if wo.alert_phase:
            d["measure_progress"] = measure_progress(db, wo.id)
        d["occurrences"] = [
            {"id": o.id, "occurred_at": o.occurred_at.isoformat() if o.occurred_at else None,
             "metric_type": o.metric_type, "indicator_type": o.indicator_type, "note": o.note}
            for o in db.query(AnomalyOccurrence)
            .filter_by(host_wo_id=wo.id)
            .order_by(AnomalyOccurrence.occurred_at.desc(), AnomalyOccurrence.id.desc()).all()
        ]
    return WorkOrderOut(**d)


def _next_code(db: Session) -> str:
    year = date.today().year
    prefix = f"RW-{year}-"
    cnt = db.query(WorkOrder).filter(WorkOrder.code.like(f"{prefix}%")).count()
    return f"{prefix}{cnt + 1:04d}"


def _project_options(
    db: Session,
    user: User | None,
    *,
    region: str | None = None,
    scope: str | None = None,
    closed_only: bool = False,
) -> list[dict]:
    """项目筛选下拉：只列当前列表里真实出现过的项目（去重）。

    与列表的「基础范围」保持一致——区域 + 行级范围 + 是否闭环，但刻意不看
    project_id / status / source / priority / person_name / search 这些二级筛选，
    避免下拉随二级条件来回弹、或出现「表里有项目但无任何工单」的死项目。
    """
    q = select(WorkOrder.project_id)
    if closed_only:
        q = q.where(WorkOrder.status == "closed")
    else:
        q = q.where(WorkOrder.status != "closed")
    if region:
        q = q.where(WorkOrder.region == region)
    if scope == "mine":
        q = apply_scope_to_query(q, db, user)
    ids = sorted({rid for (rid,) in db.execute(q.distinct()).all() if rid is not None})
    if not ids:
        return []
    projs = db.query(Project).filter(Project.id.in_(ids)).order_by(Project.name).all()
    return [{"id": p.id, "name": p.name, "region": p.region} for p in projs]


@router.get("", response_model=WorkOrderListOut)
def list_work_orders(
    project_id: int | None = None,
    source_code: str | None = None,
    status: str | None = None,
    bucket: Literal["pending", "executing", "need_backfill"] | None = None,
    priority: str | None = None,
    region: str | None = None,
    person_name: str | None = None,
    search: str | None = None,
    include_closed: bool = False,
    scope: str | None = Query(None, description="mine=按当前用户行级范围过滤（admin满量/区域PMO区域/本人）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    """主列表（活跃工作台）：已闭环工单默认归档不显示，归档视图走 /closed/list（闭环记录页）。

    include_closed=true 含归档；显式 status=closed 视为查归档，同样返回。
    scope=mine 时按登录人行级范围过滤（「我的工单」页使用）。
    """
    q = select(WorkOrder).order_by(WorkOrder.created_date.desc(), WorkOrder.id.desc())
    if project_id:
        q = q.where(WorkOrder.project_id == project_id)
    if source_code:
        q = q.where(WorkOrder.source_code == source_code)
    if status:
        q = q.where(WorkOrder.status == status)
        if status == "closed":
            include_closed = True
    if bucket == "pending":
        q = q.where(WorkOrder.status.in_(("pending", "approving")))
    elif bucket == "executing":
        q = q.where(WorkOrder.status.in_(("dispatched", "executing")))
    elif bucket == "need_backfill":
        q = q.where(
            WorkOrder.status.in_(("dispatched", "executing")),
            or_(WorkOrder.backfill_status.is_(None), WorkOrder.backfill_status != "filled"),
        )
    if not include_closed:
        q = q.where(WorkOrder.status != "closed")
    if priority:
        q = q.where(WorkOrder.priority == priority)
    if region:
        q = q.where(WorkOrder.region == region)
    if person_name:
        q = q.join(User, WorkOrder.person_id == User.id).where(User.name.ilike(f"%{person_name}%"))
    if search:
        q = q.where(WorkOrder.title.ilike(f"%{search}%"))
    if scope == "mine":
        q = apply_scope_to_query(q, db, user)

    proj_options = _project_options(db, user, region=region, scope=scope, closed_only=False)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    items = [_enrich(r, db) for r in rows]
    return WorkOrderListOut(items=items, total=total or 0, page=page, page_size=page_size, project_options=proj_options)


@router.get("/closed/list", response_model=WorkOrderListOut)
def list_closed(
    project_id: int | None = None,
    source_code: str | None = None,
    region: str | None = None,
    scope: str | None = Query(None, description="mine=按当前用户行级范围过滤（闭环记录页）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    """已闭环工单归档列表（含耗时、是否逾期）"""
    q = select(WorkOrder).where(WorkOrder.status == "closed").order_by(WorkOrder.completed_date.desc())
    if project_id:
        q = q.where(WorkOrder.project_id == project_id)
    if source_code:
        q = q.where(WorkOrder.source_code == source_code)
    if region:
        q = q.where(WorkOrder.region == region)
    if scope == "mine":
        q = apply_scope_to_query(q, db, user)
    proj_options = _project_options(db, user, region=region, scope=scope, closed_only=True)
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
    return WorkOrderListOut(items=items, total=total or 0, page=page, page_size=page_size, project_options=proj_options)


@router.get("/{wo_id}", response_model=WorkOrderOut)
def get_work_order(wo_id: int, db: Session = Depends(get_db)):
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    return _enrich(wo, db)


@router.post("", response_model=WorkOrderOut, status_code=201)
def create_work_order(body: WorkOrderCreate, db: Session = Depends(get_db), user: User | None = Depends(require_auth)):
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
    from app.services.audit import log_audit
    log_audit(db, actor_id=_actor_id(user), action="create", target_type="work_order", target_id=wo.id,
              detail={"code": wo.code, "title": wo.title})
    db.commit()
    db.refresh(wo)
    # 同步发起钉钉 OA 审批（多节点流：审批人→执行人→审批人确认）
    _launch_oa(wo, db)
    return _enrich(wo, db)


def _launch_oa(wo: WorkOrder, db: Session):
    """建单后发起钉钉 OA 审批，回填审批实例 ID。无凭证时静默占位（本地开发预期，不告警）。"""
    try:
        from app.services import dingtalk
        enriched = _enrich(wo, db)
        instance_id = dingtalk.create_oa_approval(enriched)
        if instance_id:
            wo.oa_id = instance_id
            db.commit()
        elif dingtalk.oa_configured():
            # 配置了钉钉却没生成真实实例 → 故障（如 originator_user_id 错报 820003）
            log.error("发起钉钉审批失败(已配置但未生成实例) code=%s", wo.code)
            _alert_oa_fail(wo.code)
    except Exception as e:
        log.error("发起钉钉审批异常 code=%s: %s", wo.code, e, exc_info=True)
        _alert_oa_fail(wo.code)


def _alert_oa_fail(code: str | None) -> None:
    """OA 发起失败告警（防抖按 category 收敛，避免一单一条轰炸）。"""
    try:
        from app.services.alert_service import send_alert

        send_alert(
            "工单发起钉钉审批失败",
            detail=f"工单 {code or '?'} 建单后未能生成真实 OA 审批实例",
            fix="查 backend/logs/error.log；常见根因是责任人/审批人 dingtalk_id 错（820003），"
                "核对 users.dingtalk_id 必须是 userId 而非 union_id",
            key="oa_launch_fail",
        )
    except Exception:
        pass


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


@router.patch("/{wo_id}/basic", response_model=WorkOrderOut)
def update_work_order_basic(wo_id: int, body: WorkOrderBasicUpdate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """管理员编辑工单基本信息（标题/原因/行动/结论/项目/类型/责任人/审批人/优先级/区域/三个日期）。

    不含 status（状态走流转）；字段全部可选，显式传 null 视为清空，未传保持原值。
    """
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    data = body.model_dump(exclude_unset=True)
    if "title" in data and not (data.get("title") or "").strip():
        raise HTTPException(400, "标题不能为空")
    if data.get("priority") is not None:
        data["priority"] = normalize_priority(data["priority"]) or data["priority"]
    for k, v in data.items():
        setattr(wo, k, v)
    from app.services.audit import log_audit
    log_audit(db, actor_id=_actor_id(user), action="update_basic", target_type="work_order", target_id=wo.id,
              detail={"code": wo.code, "fields": sorted(data.keys())})
    db.commit()
    db.refresh(wo)
    return _enrich(wo, db)


@router.delete("/{wo_id}")
def delete_work_order(wo_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """管理员删除工单（用于清理「起不了状态」的废单）。

    显式清理子记录并解除非级联外键引用（data_pool_items.work_order_id、
    其它工单的 triggered_wo_id），避免依赖数据库级联是否真正落库。
    """
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    # 仅允许删除「未发起 OA 审批」的废单：oa_id 为空或本地占位 "OA-" 才算未发起；
    # 已关联真实钉钉审批单的工单由 OA 流程驱动，删除会让 OA 与平台脱节，一律拦截。
    if wo.oa_id and not str(wo.oa_id).startswith("OA-"):
        raise HTTPException(409, "该工单已发起钉钉OA审批，不能删除；请在钉钉OA审批中处理")
    code, title = wo.code, wo.title

    # 1. 解除指向本工单的非级联外键
    db.query(DataPoolItem).filter(DataPoolItem.work_order_id == wo_id).update(
        {"work_order_id": None}, synchronize_session=False)
    db.query(WorkOrder).filter(WorkOrder.triggered_wo_id == wo_id).update(
        {"triggered_wo_id": None}, synchronize_session=False)

    # 2. 删除子记录（依赖顺序；级联外键这里显式删，双保险）
    db.query(AnomalyOccurrence).filter(AnomalyOccurrence.host_wo_id == wo_id).delete(synchronize_session=False)
    db.query(WorkOrderMeasureLink).filter(or_(
        WorkOrderMeasureLink.host_wo_id == wo_id,
        WorkOrderMeasureLink.measure_wo_id == wo_id,
    )).delete(synchronize_session=False)
    db.query(NotificationLog).filter(NotificationLog.work_order_id == wo_id).delete(synchronize_session=False)
    db.query(EscalationLog).filter(EscalationLog.work_order_id == wo_id).delete(synchronize_session=False)
    db.query(Attachment).filter(Attachment.work_order_id == wo_id).delete(synchronize_session=False)
    db.query(StatusLog).filter(StatusLog.work_order_id == wo_id).delete(synchronize_session=False)
    db.query(JudgmentDegradationLog).filter(JudgmentDegradationLog.work_order_id == wo_id).delete(synchronize_session=False)

    from app.services.audit import log_audit
    log_audit(db, actor_id=_actor_id(user), action="delete", target_type="work_order", target_id=wo_id,
              detail={"code": code, "title": title})
    db.delete(wo)
    db.commit()
    return {"deleted": True, "code": code}


@router.get("/{wo_id}/attachments")
def get_attachments(wo_id: int, db: Session = Depends(get_db)):
    """工单附件列表（含钉钉同步的执行附件）"""
    from app.models import Attachment
    rows = db.query(Attachment).filter_by(work_order_id=wo_id).all()
    return [{"id": a.id, "filename": a.filename, "oss_key": a.oss_key, "size": a.size,
             "created_at": a.created_at.isoformat() if a.created_at else None} for a in rows]


@router.get("/{wo_id}/attachments/{att_id}/download")
def download_attachment(wo_id: int, att_id: int, db: Session = Depends(get_db)):
    """附件下载：oss_key 存 spaceId:fileId，调钉盘 downloadInfos 换临时 url 后 302。需开通钉盘/审批下载权限。"""
    from fastapi.responses import JSONResponse, RedirectResponse
    from app.models import Attachment
    from app.services import dingtalk

    att = db.get(Attachment, att_id)
    if not att or att.work_order_id != wo_id:
        raise HTTPException(404, "附件不存在")
    fid = att.oss_key.split(":", 1)[1] if ":" in (att.oss_key or "") else (att.oss_key or "")
    wo = db.get(WorkOrder, wo_id)
    url = dingtalk.get_approval_file_download(wo.oa_id if wo else None, fid)
    if not url:
        return JSONResponse({"detail": "获取下载链接失败：需开通 qyapi_aflow_att_auth_code（审批附件下载）权限"}, status_code=502)
    return RedirectResponse(url)


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
def transition_work_order(wo_id: int, action: str, db: Session = Depends(get_db), user: User | None = Depends(require_auth)):
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
        # alert 五阶段（status 只区分 open/closed，细阶段看 alert_phase）
        "confirm_analysis": ({"judging"}, "judging", "分析结果确认·生成措施工单"),
        "dispatch_measures": ({"judging"}, "judging", "派发措施工单"),
        "confirm_recovered": ({"judging"}, "closed", "指标恢复·闭环"),
        # 重置回待派发（未发起），便于重新测试
        "reset": ({"approving", "dispatched", "executing", "verifying", "overdue", "rejected", "judging"}, "pending", "重置为待派发(未发起)"),
    }
    if action not in transitions:
        raise HTTPException(400, f"未知操作: {action}")

    # 已关联真实钉钉审批单（非本地占位 "OA-..."）的工单，状态由钉钉审批流驱动，
    # 平台手工流转只会在本地改状态、与 OA 脱节，故拦截（reset 保留作兜底）。
    _oa_driven_actions = {"dispatch", "start_exec", "submit_evidence", "close", "reject"}
    if action in _oa_driven_actions and wo.oa_id and not str(wo.oa_id).startswith("OA-"):
        raise HTTPException(409, "该工单已由钉钉OA审批流驱动，请在钉钉OA审批中更改状态")

    allowed_from, to, note = transitions[action]
    if wo.status not in allowed_from:
        raise HTTPException(409, f"当前状态 {wo.status} 不允许此操作（需 {list(allowed_from)}）")

    # alert 五阶段：按 alert_phase 校验细阶段
    _alert_phase_required = {
        "confirm_analysis": "confirming",
        "dispatch_measures": "dispatching",
        "confirm_recovered": "reexamining",
    }
    if action in _alert_phase_required:
        _required = _alert_phase_required[action]
        if wo.alert_phase != _required:
            raise HTTPException(409, f"当前阶段 {wo.alert_phase or '—'} 不允许此操作（需 {_required}）")

    prev_status = wo.status
    dispatched_measure_ids: list[int] = []
    if action == "dispatch":
        # 发起 OA 审批前强制校验必填字段（与 OA 模板必填项一致），缺失则拦截不让发起
        from app.services import dingtalk as _dingtalk
        _missing = _dingtalk.oa_required_missing(wo)
        if _missing:
            log.warning("派发被拦截 code=%s 缺：%s", wo.code, "、".join(_missing))
            raise HTTPException(422, "发起审批前请先补齐必填字段：" + "、".join(_missing))
        if not wo.oa_id:
            # 本地占位 OA 单号；若配置了钉钉则尝试发起真实 OA 审批
            wo.oa_id = "OA-" + _date.today().strftime("%Y%m%d") + "-" + str(wo.id).zfill(3)
            _ok = _enrich_oa(wo)
            if not _ok and _dingtalk.oa_configured():
                raise HTTPException(502, "发起钉钉审批失败（OA 已配置但未生成真实实例），请查看后端日志")
    if action == "reset":
        # 重置回待派发：清空 OA 单号、闭环日期、逾期与升级痕迹，便于重新发起测试
        wo.oa_id = None
        wo.completed_date = None
        wo.overdue_days = 0
        wo.escalation_level = 0
        wo.alert_phase = None
    if action == "confirm_analysis":
        # 阶段①→②：把措施草稿建成「待派发」措施工单并挂载（多对多）
        from app.services.pool_service import _create_measure_from_task
        tasks = wo.triggered_wo_tasks if isinstance(wo.triggered_wo_tasks, list) and wo.triggered_wo_tasks else None
        if not tasks or not any(isinstance(t, dict) and (t.get("title") or "").strip() for t in tasks):
            raise HTTPException(422, "尚未配置措施工单，请先在措施草稿里添加至少一条有标题的工单")
        codes = []
        for task in tasks:
            if not isinstance(task, dict) or not (task.get("title") or "").strip():
                continue
            tid = _create_measure_from_task(db, wo, task)
            m = db.get(WorkOrder, tid)
            if m:
                codes.append(m.code)
        wo.alert_phase = "dispatching"
        note = f"分析结果已确认，生成 {len(codes)} 个措施工单待派发 → {', '.join(codes)}"
    if action == "dispatch_measures":
        # 阶段②→③：把所有待派发的关联措施工单派发（发起 OA）；全派发成功才推进 tracking
        from app.services import dingtalk as _dingtalk
        from app.services.pool_service import WorkOrderMeasureLink
        links = db.query(WorkOrderMeasureLink).filter(
            WorkOrderMeasureLink.host_wo_id == wo.id,
            WorkOrderMeasureLink.removed_at.is_(None),
        ).all()
        dispatched_codes: list[str] = []
        failure_reasons: list[str] = []
        for l in links:
            m = db.get(WorkOrder, l.measure_wo_id)
            if not m or m.status == "dispatched":
                if m:
                    dispatched_codes.append(m.code)
                continue
            if m.status != "pending":
                continue
            _missing = _dingtalk.oa_required_missing(m)
            if _missing:
                failure_reasons.append(f"{m.code} 缺：{'、'.join(_missing)}")
                continue
            if not m.oa_id:
                m.oa_id = "OA-" + _date.today().strftime("%Y%m%d") + "-" + str(m.id).zfill(3)
                _ok = _enrich_oa(m)
                if not _ok and _dingtalk.oa_configured():
                    failure_reasons.append(f"{m.code} 发起钉钉审批失败")
                    continue
            m.status = "dispatched"
            db.add(StatusLog(work_order_id=m.id, from_status="pending", to_status="dispatched",
                             note=f"由异常主单 {wo.code} 派发·发起OA审批"))
            dispatched_codes.append(m.code)
            dispatched_measure_ids.append(m.id)
        if failure_reasons:
            log.warning("派发措施工单被拦截 host=%s：%s", wo.code, "；".join(failure_reasons))
            raise HTTPException(422, "部分措施工单无法派发，请先补齐：" + "；".join(failure_reasons))
        if not dispatched_codes:
            log.warning("派发措施工单无可用项 host=%s", wo.code)
            raise HTTPException(422, "没有可派发的措施工单")
        wo.alert_phase = "tracking"
        note = f"已派发 {len(dispatched_codes)} 个措施工单 → {', '.join(dispatched_codes)}"
    db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=to, note=note))
    from app.services.audit import log_audit
    log_audit(db, actor_id=_actor_id(user), action="transition", target_type="work_order", target_id=wo.id,
              detail={"action": action, "from": prev_status, "to": to})
    wo.status = to
    if to == "closed":
        if wo.source_code == "alert" and wo.alert_phase:
            # 异常主单闭环（confirm_recovered 或「无需措施直接闭环」）
            wo.alert_phase = "recovered"
        else:
            # 措施类工单闭环 → 回写关联异常主单进度（2/11 / 全闭环置待复核）
            from app.services.pool_service import _notify_measure_closed
            _notify_measure_closed(db, wo)
    if to == "closed" and not wo.completed_date:
        wo.completed_date = _date.today()
        if not wo.conclusion:
            wo.conclusion = "验收通过"
    if to == "closed" and wo.deadline and wo.completed_date and wo.completed_date > wo.deadline:
        wo.overdue_days = (wo.completed_date - wo.deadline).days
    db.commit()
    # 措施工单批量派发后，按「完成人=异常主单责任人」通报（场景2）
    if dispatched_measure_ids:
        from app.services.notification_service import trigger_measure_dispatch
        trigger_measure_dispatch(wo.id, dispatched_measure_ids)
    db.refresh(wo)
    # 异步触发通知（开发环境 Celery eager 同步执行）
    _trigger_notify(wo.id, action, to)
    return _enrich(wo, db)


class _RedispatchMeasure(BaseModel):
    title: str
    person_name: str | None = None
    type_id: int | None = None
    planned_start_date: date | None = None
    deadline: date | None = None
    reason: str | None = None
    action: str | None = None
    priority: str | None = None


class _RedispatchRequest(BaseModel):
    measures: list[_RedispatchMeasure]


class _ReuseRequest(BaseModel):
    measure_ids: list[int]


class _MergeRequest(BaseModel):
    target_host_id: int


@router.post("/{wo_id}/redispatch", response_model=WorkOrderOut)
def redispatch_measures(wo_id: int, body: _RedispatchRequest, db: Session = Depends(get_db), user: User | None = Depends(require_auth)):
    """阶段④指标异常 → 手动补派发新措施工单 → 回到③跟踪（redispatch）。"""
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    if wo.source_code != "alert" or not wo.alert_phase:
        raise HTTPException(400, "仅异常指标主单支持补派发")
    if wo.alert_phase != "reexamining":
        raise HTTPException(409, f"当前阶段 {wo.alert_phase} 不允许补派发（需 reexamining）")

    from app.services.pool_service import _create_measure_from_task
    from app.services import dingtalk as _dingtalk

    codes = []
    failures = []
    for m in body.measures:
        if not (m.title or "").strip():
            continue
        task = {
            "title": m.title, "person_name": m.person_name, "type_id": m.type_id,
            "deadline": m.deadline.isoformat() if m.deadline else None,
            "reason": m.reason, "action": m.action, "priority": m.priority,
        }
        tid = _create_measure_from_task(db, wo, task, link_source="manual")
        measure = db.get(WorkOrder, tid)
        if m.planned_start_date is not None:
            measure.planned_start_date = m.planned_start_date

        _missing = _dingtalk.oa_required_missing(measure)
        if _missing:
            failures.append(f"{measure.code} 缺：{'、'.join(_missing)}")
            continue
        if not measure.oa_id:
            measure.oa_id = "OA-" + date.today().strftime("%Y%m%d") + "-" + str(measure.id).zfill(3)
            _enrich_oa(measure)
        measure.status = "dispatched"
        db.add(StatusLog(work_order_id=measure.id, from_status="pending", to_status="dispatched",
                         note=f"由异常主单 {wo.code} 复核补派发·发起OA审批"))
        codes.append(measure.code)

    if failures:
        raise HTTPException(422, "部分措施工单无法派发：" + "；".join(failures))
    if not codes:
        raise HTTPException(422, "没有可派发的措施工单")

    from app.services.audit import log_audit
    wo.alert_phase = "tracking"
    db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=wo.status,
                     note=f"指标复核未达标·补派发 {len(codes)} 个措施工单，回到跟踪"))
    log_audit(db, actor_id=_actor_id(user), action="transition", target_type="work_order", target_id=wo.id,
              detail={"action": "redispatch", "measures": codes})
    db.commit()
    db.refresh(wo)
    return _enrich(wo, db)


@router.get("/{wo_id}/similar")
def similar_hosts(wo_id: int, db: Session = Depends(get_db)):
    """同类开着的主单（同项目 + 同指标大类），供「合并 / 挂载复用」选择。"""
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    if wo.source_code != "alert" or not wo.metric_type:
        return {"items": []}
    from app.services.pool_service import measure_progress
    rows = db.query(WorkOrder).filter(
        WorkOrder.source_code == "alert",
        WorkOrder.metric_type == wo.metric_type,
        WorkOrder.project_id == wo.project_id,
        WorkOrder.status != "closed",
        WorkOrder.alert_phase.isnot(None),
        WorkOrder.id != wo.id,
    ).all()
    items = []
    for h in rows:
        items.append({
            "id": h.id, "code": h.code, "title": h.title, "alert_phase": h.alert_phase,
            "measure_progress": measure_progress(db, h.id),
        })
    return {"items": items}


@router.post("/{wo_id}/reuse", response_model=WorkOrderOut)
def reuse_measures(wo_id: int, body: _ReuseRequest, db: Session = Depends(get_db), user: User | None = Depends(require_auth)):
    """把其它主单开着的措施工单挂载到本主单（复用，多对多新增关联）。"""
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(404, "工单不存在")
    if wo.source_code != "alert" or not wo.alert_phase or wo.status == "closed":
        raise HTTPException(400, "仅开着且未闭环的异常指标主单支持挂载复用")
    from app.services.pool_service import _link_measure, measure_progress
    from app.services.audit import log_audit
    mounted = []
    for mid in body.measure_ids:
        m = db.get(WorkOrder, mid)
        if not m or m.status == "closed":
            continue
        dup = db.query(WorkOrderMeasureLink).filter_by(
            host_wo_id=wo.id, measure_wo_id=mid, removed_at=None).first()
        if dup:
            continue
        _link_measure(db, wo.id, mid, "reused")
        mounted.append(m.code)
    db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status=wo.status,
                     note=f"挂载复用 {len(mounted)} 个措施工单 → {', '.join(mounted)}"))
    log_audit(db, actor_id=_actor_id(user), action="reuse", target_type="work_order", target_id=wo.id,
              detail={"measures": mounted})
    db.commit()
    db.refresh(wo)
    return _enrich(wo, db)


@router.post("/{wo_id}/merge")
def merge_into_host(wo_id: int, body: _MergeRequest, db: Session = Depends(get_db), user: User | None = Depends(require_auth)):
    """把本异常主单合并进另一条开着的主单（同项目同类）：发生记录移过去，本单闭环。"""
    source = db.get(WorkOrder, wo_id)
    if not source:
        raise HTTPException(404, "工单不存在")
    target = db.get(WorkOrder, body.target_host_id)
    if not target:
        raise HTTPException(404, "目标主单不存在")
    if source.id == target.id:
        raise HTTPException(400, "不能合并到自己")
    if target.status == "closed" or not target.alert_phase:
        raise HTTPException(400, "目标主单必须开着且为异常主单")
    if source.status == "closed":
        raise HTTPException(400, "本单已闭环，不能合并")

    from app.services.audit import log_audit
    # 把 source 的发生记录迁到 target，并补一条合并记录
    moved = 0
    for occ in db.query(AnomalyOccurrence).filter_by(host_wo_id=source.id).all():
        occ.host_wo_id = target.id
        moved += 1
    db.add(AnomalyOccurrence(
        host_wo_id=target.id, occurred_at=date.today(),
        metric_type=source.metric_type,
        indicator_type=(source.triggered_wo_title or source.title)[:128],
        pool_item_id=source.parent_pool_id,
        note=f"合并自 {source.code}",
    ))
    source.status = "closed"
    source.alert_phase = "recovered"
    source.completed_date = date.today()
    source.conclusion = f"已合并入 {target.code}"
    db.add(StatusLog(work_order_id=source.id, from_status="judging", to_status="closed",
                     note=f"合并入 {target.code}"))
    db.add(StatusLog(work_order_id=target.id, from_status=target.status, to_status=target.status,
                     note=f"吸收合并 {source.code}（发生记录 {moved} 条移入）"))
    log_audit(db, actor_id=_actor_id(user), action="merge", target_type="work_order", target_id=target.id,
              detail={"source": source.code, "moved_occurrences": moved})
    db.commit()
    db.refresh(target)
    return _enrich(target, db)


def _enrich_oa(wo: WorkOrder, db: Session | None = None) -> bool:
    """尝试发起钉钉 OA 审批，回填真实 OA 实例 ID。返回是否成功。"""
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
        return bool(instance_id)
    except Exception as e:
        print(f"[workorder] OA 发起异常: {e}")
        return False


def _trigger_notify(wo_id: int, action: str, to_status: str):
    """流转后触发通知。派发走「群合并」；其余事件走工作通知路径。"""
    if action == "dispatch":
        from app.services.notification_service import trigger_dispatch_group
        trigger_dispatch_group([wo_id])
        return
    from app.services.notification_service import trigger_notify
    event_map = {
        "submit_evidence": "sla_warn",  # 待验收提醒审批人
        "close": "dispatch",  # 闭环通知（复用 dispatch 模板，实际可单独配）
    }
    event = event_map.get(action)
    if event:
        trigger_notify(wo_id, event)


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
            wo.alert_phase = "confirming"  # 进入五阶段①：分析结果确认
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
