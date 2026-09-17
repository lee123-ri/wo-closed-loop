"""导入接口：听记解析 + 表格批量导入"""
import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security_middleware import limiter

from app.core.database import get_db
from app.models import Project, User, WorkOrder, WorkOrderTypeKB, StatusLog, AgentImportBatch, AnomalyOccurrence
from app.services.llm_service import parse_minutes
from app.services.priority_service import match_priority
from app.services.project_names import clean_project_name
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


# ── 表格批量导入：CSV / Excel 统一入口 ─────────────────────────────

# 列名归一：表头中文/英文同义 → 规范字段
HEADER_ALIASES: list[tuple[str, list[str]]] = [
    ("title", ["title", "标题", "工单标题", "名称", "事项"]),
    ("project", ["project", "项目", "项目名称"]),
    ("person", ["person", "责任人", "负责人", "处理人", "责任部门"]),
    ("deadline", ["deadline", "截止日期", "截止时间", "完成时间", "计划完成"]),
    ("type", ["type", "类型", "工单类型"]),
    ("reason", ["reason", "触发原因", "描述", "问题描述", "根因", "原因"]),
    ("action", ["action", "行动要求", "行动", "措施", "干什么", "整改措施"]),
]


def _canonical_head(raw_header: str) -> str | None:
    h = (raw_header or "").strip().lower().lstrip("﻿")
    if not h:
        return None
    for canon, aliases in HEADER_ALIASES:
        if h in (a.lower() for a in aliases):
            return canon
    return None


def _normalize_row(raw: dict) -> dict:
    out: dict[str, str] = {}
    for k, v in raw.items():
        canon = _canonical_head(str(k))
        if canon and canon not in out:
            out[canon] = (v or "").strip()
    return out


def _read_csv_rows(raw: bytes) -> list[dict]:
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("gbk", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    return [dict(r) for r in reader if any((v or "").strip() for v in r.values())]


def _read_excel_rows(raw: bytes) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    hdr_idx = next((i for i, r in enumerate(rows) if any(c is not None and str(c).strip() for c in r)), None)
    if hdr_idx is None:
        return []
    header = [str(c).strip() if c is not None else "" for c in rows[hdr_idx]]
    data: list[dict] = []
    for r in rows[hdr_idx + 1:]:
        if not any(c is not None and str(c).strip() for c in r):
            continue
        row: dict[str, str] = {}
        for j, h in enumerate(header):
            if not h:
                continue
            val = r[j] if j < len(r) else None
            row[h] = "" if val is None else str(val).strip()
        data.append(row)
    return data


def _read_table_rows(raw: bytes, filename: str) -> list[dict]:
    """按文件名/魔数判定 CSV 或 Excel，解析成原始行（表头原文 → 值）。

    xlsx/xlsm/xls 走 openpyxl；其余走 CSV。两者结果再经 _normalize_row 归一成规范字段。
    """
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")) or raw[:2] == b"PK" or raw[:4] == b"\xd0\xcf\x11\xe0":
        return _read_excel_rows(raw)
    return _read_csv_rows(raw)


def _project_indexes(db: Session) -> tuple[dict[str, Project], dict[str, Project]]:
    """建两份项目索引：规范名 → 项目、编码 → 项目。

    规范名按 clean_project_name 归一，这样模板里写「国电投别力古台500MW-YH」也能匹配到
    库里「国电投别力古台500MW」（历史曾因精确匹配后缀漂移而丢项目名）。同名规范化碰撞时
    优先活动项、再取 id 小者，保证确定性。
    """
    by_name: dict[str, list[Project]] = {}
    by_code: dict[str, Project] = {}
    for p in db.query(Project).all():
        by_code.setdefault(p.code, p)
        key = clean_project_name(p.name)
        if key:
            by_name.setdefault(key, []).append(p)
    resolved: dict[str, Project] = {}
    for key, members in by_name.items():
        members.sort(key=lambda p: (not p.is_active, p.id))
        resolved[key] = members[0]
    return resolved, by_code


def _resolve_project(raw: str, by_name: dict[str, Project], by_code: dict[str, Project]) -> Project | None:
    """项目名/编码 → 项目：先规范名（可容纳后缀），再按编码兜底。空输入返回 None。"""
    s = (raw or "").strip()
    if not s:
        return None
    key = clean_project_name(s)
    if key and key in by_name:
        return by_name[key]
    return by_code.get(s)


def _resolve_deadline(deadline_str: str, priority: str) -> date:
    """截止日期解析：非法/过早 → 按优先级兜底（与 _import_rows 落库口径一致）。"""
    deadline = None
    try:
        d = deadline_str.replace("/", "-")[:10]
        deadline = date.fromisoformat(d) if d else None
        if deadline and deadline.year < 1900:
            deadline = None
    except ValueError:
        deadline = None
    if deadline is None:
        deadline = date.today() + timedelta(days={"P1": 1, "P2": 3, "P3": 7}.get(priority, 7))
    return deadline


def _preview_rows(db: Session, rows: list[dict]) -> dict:
    """导入预览：解析+归一+resolve，不落库。逐行给 ok/error，供前端「确认录入」勾选。

    ok=false 的行在确认落库时会被 _import_rows 跳过：缺标题、缺项目、项目未匹配。
    责任人/类型未匹配只标 warning（person_ok/type_ok=false），落库时留空，不算错误。
    """
    users = {u.name: u for u in db.query(User).all()}
    projects_by_name, projects_by_code = _project_indexes(db)
    type_kbs = {t.name: t for t in db.query(WorkOrderTypeKB).all()}

    out: list[dict] = []
    for i, raw in enumerate(rows, 2):
        row = _normalize_row(raw)
        title = row.get("title", "").strip()
        item: dict = {
            "line": i, "title": title,
            "reason": row.get("reason", "").strip(),
            "action": row.get("action", "").strip(),
            "raw": row,  # canonical 行，前端确认后原样回传
            "ok": True, "error": None,
        }
        if not title:
            item["ok"] = False
            item["error"] = "缺少标题"
            out.append(item)
            continue

        project_name = row.get("project", "").strip()
        person_name = row.get("person", "").strip()
        type_name = row.get("type", "").strip()

        project = _resolve_project(project_name, projects_by_name, projects_by_code)
        person = users.get(person_name) if person_name else None
        type_kb = type_kbs.get(type_name) if type_name else None

        item["project_name"] = project_name
        item["project_id"] = project.id if project else None
        item["project_label"] = f"{project.code} · {project.name}" if project else None
        item["person_name"] = person_name
        item["person_ok"] = bool(person) or not person_name
        item["type_name"] = type_name
        item["type_ok"] = bool(type_kb) or not type_name

        priority = match_priority(db, f"{title} {row.get('reason', '')}", "manual")
        item["priority"] = priority
        item["deadline"] = _resolve_deadline(row.get("deadline", "").strip(), priority).isoformat()

        if not project:
            item["ok"] = False
            item["error"] = "项目未匹配" if project_name else "缺少项目"
        out.append(item)

    ok_n = sum(1 for x in out if x["ok"])
    return {"total": len(out), "ok_count": ok_n, "err_count": len(out) - ok_n, "rows": out}


def _import_rows(db: Session, rows: list[dict]) -> tuple[int, list[str]]:
    created = 0
    errors: list[str] = []
    year = date.today().year
    existing_codes = [c for (c,) in db.query(WorkOrder.code).filter(WorkOrder.code.like(f"RW-{year}-%")).all()]
    seq = max([int(c.rsplit("-", 1)[-1]) for c in existing_codes if c.rsplit("-", 1)[-1].isdigit()], default=0) + 1
    users = {u.name: u for u in db.query(User).all()}
    projects_by_name, projects_by_code = _project_indexes(db)
    type_kbs = {t.name: t for t in db.query(WorkOrderTypeKB).all()}

    for i, raw in enumerate(rows, 2):
        row = _normalize_row(raw)
        title = row.get("title", "").strip()
        if not title:
            errors.append(f"第{i}行：缺少标题")
            continue
        person_name = row.get("person", "")
        project_name = row.get("project", "").strip()
        type_name = row.get("type", "")

        person = users.get(person_name) if person_name else None
        project = _resolve_project(project_name, projects_by_name, projects_by_code)
        type_kb = type_kbs.get(type_name) if type_name else None

        # 项目必填且须能解析到已有项目：否则静默落空 → 列表「无项目名」（历史 bug），这里显式跳过
        if not project:
            if project_name:
                errors.append(f"第{i}行：项目「{project_name}」未匹配（请用项目台账规范名或 PRJ-xxxx 编码）")
            else:
                errors.append(f"第{i}行：缺少项目")
            continue

        priority = match_priority(db, f"{title} {row.get('reason', '')}", "manual")
        deadline = _resolve_deadline(row.get("deadline", "").strip(), priority)

        code = f"RW-{year}-{seq:04d}"
        seq += 1

        wo = WorkOrder(
            code=code, title=title,
            reason=(row.get("reason") or "表格导入").strip(),
            action=(row.get("action") or title).strip(),
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
    return created, errors


@router.post("/table")
@limiter.limit("10/minute")
async def import_table(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传 CSV/Excel 批量导入（列名中文/英文同义自适应）。

    支持列：标题/项目/责任人/截止日期/类型/描述/行动要求（含英文别名 title/project/person/
    deadline/type/reason/action）。xlsx/xls 读第一个 sheet；CSV 自动检测 UTF-8 BOM / GBK。
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    try:
        rows = _read_table_rows(raw, file.filename or "")
    except Exception as e:
        raise HTTPException(400, "无法解析该文件：请使用 .xlsx 或 CSV（旧版 .xls 请先另存为 .xlsx 再导入）")
    if not rows:
        raise HTTPException(400, "无数据行（请确认表头为：标题/项目/责任人/截止日期/类型/描述/行动要求）")
    created, errors = _import_rows(db, rows)
    return {"created": created, "errors": errors, "total": len(rows)}


class TableConfirmIn(BaseModel):
    rows: list[dict]


@router.post("/table/preview")
@limiter.limit("10/minute")
async def preview_table(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传 CSV/Excel → 解析预览（不落库），返回每行 ok/error，供前端「确认录入」勾选。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    try:
        rows = _read_table_rows(raw, file.filename or "")
    except Exception as e:
        raise HTTPException(400, "无法解析该文件：请使用 .xlsx 或 CSV（旧版 .xls 请先另存为 .xlsx 再导入）")
    if not rows:
        raise HTTPException(400, "无数据行（请确认表头为：标题/项目/责任人/截止日期/类型/描述/行动要求）")
    return _preview_rows(db, rows)


@router.post("/table/confirm")
@limiter.limit("10/minute")
def confirm_table(request: Request, body: TableConfirmIn, db: Session = Depends(get_db)):
    """确认录入：接收预览阶段勾选的原始行（raw），复用 _import_rows 落库。"""
    if not body.rows:
        raise HTTPException(400, "无可导入的行")
    created, errors = _import_rows(db, body.rows)
    return {"created": created, "errors": errors, "total": len(body.rows)}


@router.get("/template")
@limiter.limit("20/minute")
def download_template(request: Request):
    """下载工单导入模板（xlsx）：表头 + 1 行示例。"""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    headers = ["标题", "项目", "责任人", "截止日期", "类型", "描述", "行动要求"]
    example = ["示例：更换#1风机齿轮箱油封", "示例项目（替换为实际项目名）",
               "张三（替换为实际责任人姓名）", "2026-09-20", "检修工单", "巡检发现齿轮箱渗油", "更换油封并复检"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "工单导入"
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
    ws.append(example)
    for c, w in enumerate([30, 26, 24, 12, 12, 28, 28], 1):
        ws.column_dimensions[get_column_letter(c)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="workorder_import_template.xlsx"'},
    )


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
        alert_phase="confirming",  # 进入五阶段①：分析结果确认
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
    # 异常主单：记一条「发生记录」
    db.add(AnomalyOccurrence(
        host_wo_id=wo.id,
        occurred_at=date.today(),
        metric_type=None,
        indicator_type=indicator or None,
        note="可靠性Agent导入",
    ))

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
