"""导入接口：听记解析 + 表格批量导入"""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security_middleware import limiter

from app.core.database import get_db
from app.models import Project, User, WorkOrder, WorkOrderTypeKB, StatusLog, AgentImportBatch
from app.services.llm_service import parse_minutes
from app.services.priority_service import match_priority
from datetime import date, datetime, timedelta, timezone

router = APIRouter(prefix="/import", tags=["import"])


class MinutesIn(BaseModel):
    text: str


@router.post("/parse-minutes")
@limiter.limit("20/minute")
def parse_minutes_api(request: Request, body: MinutesIn):
    """智能解析听记内容"""
    if not body.text.strip():
        raise HTTPException(400, "内容为空")
    return parse_minutes(body.text)


@router.post("/table")
@limiter.limit("10/minute")
async def import_table(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传 CSV/Excel 批量导入。

    支持列：title, project, person, deadline, type, reason, action
    CSV 编码自动检测 UTF-8 BOM。
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("gbk", errors="ignore")

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        raise HTTPError("CSV 无数据行")

    created = 0
    errors: list[str] = []
    for i, row in enumerate(rows, 2):
        title = (row.get("title") or row.get("标题") or "").strip()
        if not title:
            errors.append(f"第{i}行：缺少标题")
            continue
        person_name = (row.get("person") or row.get("责任人") or "").strip()
        project_name = (row.get("project") or row.get("项目") or "").strip()
        deadline_str = (row.get("deadline") or row.get("截止日期") or "").strip()

        person = db.query(User).filter(User.name == person_name).first() if person_name else None
        project = db.query(Project).filter(Project.name == project_name).first() if project_name else None
        type_kb = db.query(WorkOrderTypeKB).filter(WorkOrderTypeKB.name == (row.get("type") or "")).first()

        priority = match_priority(db, f"{title} {row.get('reason','')}", "manual")
        deadline = None
        if deadline_str:
            try:
                deadline = date.fromisoformat(deadline_str)
            except ValueError:
                deadline = date.today() + timedelta(days={"P1": 1, "P2": 3, "P3": 7}.get(priority, 7))
        else:
            deadline = date.today() + timedelta(days={"P1": 1, "P2": 3, "P3": 7}.get(priority, 7))

        year = date.today().year
        cnt = db.query(WorkOrder).filter(WorkOrder.code.like(f"RW-{year}-%")).count()
        code = f"RW-{year}-{cnt + 1:04d}"

        wo = WorkOrder(
            code=code, title=title,
            reason=(row.get("reason") or row.get("触发原因") or "表格导入").strip(),
            action=(row.get("action") or row.get("行动要求") or title).strip(),
            project_id=project.id if project else None,
            person_id=person.id if person else None,
            approver_id=type_kb.default_approver_id if type_kb else None,
            type_id=type_kb.id if type_kb else None,
            source_code="manual", status="pending", priority=priority,
            created_date=date.today(), deadline=deadline,
        )
        db.add(wo)
        db.flush()
        db.add(StatusLog(work_order_id=wo.id, from_status=None, to_status="pending", note="表格导入"))
        created += 1
    db.commit()
    return {"created": created, "errors": errors, "total": len(rows)}


# ── 可靠性Agent《指标异常处置SOP》出参导入 ──────────────────────────
# 契约见 docs/reliability-agent/workorder.schema.json。
# 原则（人工兜底）：能映射的字段自动填；映射不到（如责任人「远景能源」是组织、
# 查不到 userId）就留空，由确认人补填。建 status=pending 草稿，不自动派发。

class AgentPersonIn(BaseModel):
    name: str
    role: str | None = None


class AgentWorkOrderIn(BaseModel):
    workorder_id: str
    title: str
    subtype: str | None = None
    oa_type: str | None = None
    reason: str = ""
    action: str = ""
    target_metric: str | None = None
    responsible: AgentPersonIn | None = None
    approver: AgentPersonIn | None = None
    deadline_days: int = 7
    deadline_basis: str | None = None
    completion_criteria: str | None = None


class AgentTriggerIn(BaseModel):
    indicator: str | None = None
    period: str | None = None


class AgentWorkOrderBatchIn(BaseModel):
    project: str
    trigger: AgentTriggerIn | None = None
    workorders: list[AgentWorkOrderIn]


def _import_agent_batch(db: Session, body: AgentWorkOrderBatchIn) -> dict:
    """核心导入逻辑：出参批次 → 1 条「异常指标」宿主工单 + N 条措施草稿。

    可靠性Agent的复盘出参里，每条 workorder 其实是一条「措施」（SMART 工单），整体对应一次
    「异常指标」分析。这里合并为：1 条宿主工单（alert、判定中）+ N 条措施草稿
    （triggered_wo_tasks），由 PMO 在判断界面人工选择工单类型后点「生成措施工单并闭环」上列表，
    不能直接把措施草稿撒到工单列表。

    批次去重：项目+指标+周期 构成 batch_key，同批次重导直接跳过整批。
    """
    project = db.query(Project).filter(Project.name == body.project).first()

    # 批次去重：项目|指标|周期
    indicator = (body.trigger.indicator if body.trigger else None) or ""
    period = (body.trigger.period if body.trigger else None) or ""
    batch_key = "|".join([body.project or "", indicator, period])
    existing_batch = db.query(AgentImportBatch).filter(AgentImportBatch.batch_key == batch_key).first()
    if existing_batch:
        return {
            "created": 0, "skipped_duplicate": len(body.workorders), "batch_key": batch_key,
            "already_imported": True,
            "message": f"该批次（{body.project} / {indicator or '—'} / {period or '—'}）已导入过，跳过",
            "results": [],
        }

    # 每条出参 workorder → 措施工单草稿（工单类型/责任人由 PMO 在判断界面人工补选）
    tasks: list[dict] = []
    for wo_in in body.workorders:
        action_text = wo_in.action or ""
        if wo_in.target_metric:
            action_text = f"{action_text}\n【目标】{wo_in.target_metric}"
        person_name = ""
        if wo_in.responsible and wo_in.responsible.name:
            u = db.query(User).filter(User.name == wo_in.responsible.name).first()
            person_name = (u.name if u else wo_in.responsible.name) or ""
        deadline = date.today() + timedelta(days=max(wo_in.deadline_days, 0))
        tasks.append({
            "title": (wo_in.title or "")[:256],
            "reason": wo_in.reason or "",
            "action": action_text,
            "person_name": person_name,
            "deadline": deadline.isoformat(),
            "priority": "P1",
            "type_id": None,  # 由 PMO 人工选择，不默认成异常指标类
            "subtype": wo_in.subtype or "",
        })

    # 宿主工单类型：oa_type -> WorkOrderTypeKB（仅宿主；措施类型由人工逐条选）
    first = body.workorders[0] if body.workorders else None
    host_type_kb = None
    for tname in ((first.oa_type if first else None), "设备预警工单", "其他"):
        if not tname:
            continue
        host_type_kb = db.query(WorkOrderTypeKB).filter(WorkOrderTypeKB.name == tname).first()
        if host_type_kb:
            break
    host_approver = db.get(User, host_type_kb.default_approver_id) if host_type_kb else None

    title = f"【指标异常处置】{indicator or '—'}" + (f"（{period}）" if period else "")
    reason_text = f"{indicator or '—'} 指标在 {period or '—'} 出现异常，经可靠性Agent归因分析，需生成措施工单整改。"
    action_text = "\n".join(f"{i + 1}. {t['title']}" for i, t in enumerate(tasks)) or "可靠性Agent复盘措施"

    host_deadline = None
    deadlines = [t["deadline"] for t in tasks if t.get("deadline")]
    if deadlines:
        try:
            host_deadline = max(date.fromisoformat(d) for d in deadlines)
        except ValueError:
            host_deadline = None

    year = date.today().year
    cnt = db.query(WorkOrder).filter(WorkOrder.code.like(f"RW-{year}-%")).count()
    code = f"RW-{year}-{cnt + 1:04d}"

    wo = WorkOrder(
        code=code, title=title,
        reason=reason_text, action=action_text,
        project_id=project.id if project else None,
        person_id=None,
        approver_id=host_approver.id if host_approver else None,
        type_id=host_type_kb.id if host_type_kb else None,
        source_code="alert", status="judging", priority="P1",
        region=project.region if project else None,
        created_date=date.today(),
        deadline=host_deadline or (date.today() + timedelta(days=7)),
        backfill_status="filled", backfill_reason=reason_text, backfill_action=action_text,
        backfilled_at=datetime.now(timezone.utc),
        triggered_wo_tasks=tasks,
        judgment_status="judging",
    )
    db.add(wo)
    db.flush()

    unmapped = []
    if not project:
        unmapped.append(f"项目({body.project})")
    if not host_type_kb:
        unmapped.append(f"工单类型({(first.oa_type if first else '未给')})")
    missing_person = sum(1 for t in tasks if not t["person_name"])
    if missing_person:
        unmapped.append(f"责任人({missing_person}条措施未匹配)")

    note = f"可靠性Agent导入·进入判断流程（{len(tasks)}条措施草稿待生成）"
    if unmapped:
        note += "；留空待人工补填：" + "、".join(unmapped)
    db.add(StatusLog(work_order_id=wo.id, from_status=None, to_status="judging", note=note))

    results = [{
        "workorder_id": batch_key, "code": code, "status": "created",
        "task_count": len(tasks), "unmapped": unmapped,
    }]

    db.add(AgentImportBatch(
        batch_key=batch_key,
        project_name=body.project,
        metric_type=indicator or None,
        period=period or None,
        source_system="指标异常处置SOP",
        work_order_codes=[code],
    ))

    db.commit()
    return {"created": 1, "skipped_duplicate": 0, "total": len(body.workorders),
            "batch_key": batch_key, "results": results}


@router.post("/agent-workorders")
@limiter.limit("10/minute")
def import_agent_workorders(request: Request, body: AgentWorkOrderBatchIn, db: Session = Depends(get_db)):
    """导入可靠性Agent出参 JSON（已结构化的 workorders schema）。"""
    return _import_agent_batch(db, body)


class AgentHtmlIn(BaseModel):
    html: str


@router.post("/agent-html")
@limiter.limit("10/minute")
def import_agent_html(request: Request, body: AgentHtmlIn, db: Session = Depends(get_db)):
    """导入可靠性Agent的复盘 HTML：先解析成出参 JSON，再走同一套入库逻辑。

    解析器见 app/services/agent_html_parser.py。解析结果以 parsed 字段回传，便于核对。
    """
    from app.services.agent_html_parser import parse_agent_html
    batch_data = parse_agent_html(body.html)
    parsed = batch_data["workorders"]
    if not parsed:
        raise HTTPException(400, "未从 HTML 解析出任何工单（可能不是指标异常处置的复盘 HTML）")
    batch = AgentWorkOrderBatchIn(**batch_data)
    result = _import_agent_batch(db, batch)
    result["parsed_count"] = len(parsed)
    result["project"] = batch_data["project"]
    result["trigger"] = batch_data["trigger"]
    return result


def HTTPError(msg):  # 兼容 helper
    return HTTPException(400, msg)
