"""钉盘「工单版」xlsx → 软工单导入。

数据源：钉盘上各项目年度运营计划的「工单版」xlsx（`目标→拆解→工单` sheet）。
流程：dws 搜「工单版」文件 → 下载 → 按表头自适应解析（煜特/师宗两套列结构）→ 导入工单(source=plan)。
"""
from __future__ import annotations

import calendar
import json
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import openpyxl

from app.core.database import SessionLocal
from app.models import Project, StatusLog, User, WorkOrder
from app.services.workorder_code import next_work_order_code


def _dws(*args: str) -> dict:
    r = subprocess.run(["dws", *args, "--format", "json"], capture_output=True, text=True, timeout=180)
    out = r.stdout.strip()
    if not out:
        raise RuntimeError(f"dws 空输出: {r.stderr[:200]}")
    return json.loads(out)


def find_workorder_versions() -> list[dict]:
    """搜索钉盘年度计划工单 xlsx（「年度运营计划工单」完整版 + 「工单版」），汇总去重。"""
    files: list[dict] = []
    seen: set[str] = set()
    for kw in ("运营计划工单", "工单版", "资管项目运营计划"):
        try:
            data = _dws("drive", "+find-file", "--query", kw)
        except Exception:
            continue
        for f in data.get("files", []):
            fid = f.get("dentryId") or f.get("fileId")
            if f.get("type") != "FILE" or not fid or fid in seen:
                continue
            seen.add(fid)
            files.append({"name": f.get("name"), "fileId": fid})
    return files


def _download(file_id: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="wo_drive_"))
    subprocess.run(
        ["dws", "drive", "download", "--node", file_id, "--output", str(tmp)],
        capture_output=True, text=True, timeout=180,
    )
    xs = list(tmp.glob("*.xlsx")) + list(tmp.glob("*.xls"))
    return xs[0] if xs else tmp


def _map_priority(p: str) -> str:
    if not p:
        return "P2"
    m = re.match(r"P(\d)", str(p).strip())
    if not m:
        return "P2"
    return {"0": "P1", "1": "P2", "2": "P3"}.get(m.group(1), "P2")


def _parse_deadline(s: str) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    # 日期字符串：2026-10-01 / 2026-10-01 00:00:00
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # 月份写法：7月 / 7-9月 / 2027年2-3月
    year = 2027 if "2027" in s else 2026
    months = [int(x) for x in re.findall(r"(\d{1,2})\s*月", s)]
    if months:
        mm = max(min(x, 12) for x in months)
    elif any(k in s for k in ("持续", "每月", "按需", "季度")):
        mm = 12
    else:
        return date(2026, 12, 31)
    return date(year, mm, calendar.monthrange(year, mm)[1])


def _detect_carrier_col(data_rows: list[tuple]) -> int | None:
    """按数值扫描 EAM/非EAM 标记列：某列非空值全部是 EAM/非EAM 即命中（≥3 个非空）。"""
    ncols = max((len(r) for r in data_rows), default=0)
    for j in range(ncols):
        vals = [str(r[j]).strip() for r in data_rows if j < len(r) and r[j] not in (None, "")]
        if len(vals) >= 3 and all(v in ("EAM", "非EAM") for v in vals):
            return j
    return None


def _parse_sheet(file_path: Path) -> list[dict]:
    """解析年度计划工单 sheet，兼容两种模板：

    A. 工单型（中建投/协合）：「工单编号 WO-xxx」+「工单载体」列，表含「目标→拆解→工单」
    B. 资管型（泰康）：「类别/序号/详细措施」结构，EAM/非EAM 标记在某个「备注」列

    载体标记列优先取表头含「载体/EAM」的列；否则按数值扫描 EAM/非EAM 列。
    """
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheet = next((ws for ws in wb.worksheets if "目标" in ws.title or "工单" in ws.title or "计划" in ws.title), None) \
        or wb.worksheets[0]
    rows = [list(r) for r in sheet.iter_rows(values_only=True)]

    hdr_idx = None
    for i, row in enumerate(rows):
        if row and any(c and any(k in str(c) for k in ("工单编号", "详细措施", "工单名称", "工单内容")) for c in row):
            hdr_idx = i
            break
    if hdr_idx is None:
        return []

    header = [str(c).strip() if c is not None else "" for c in rows[hdr_idx]]

    def col(*keys: str) -> int | None:
        for k in keys:
            for i, h in enumerate(header):
                if k in h:
                    return i
        return None

    wo_code_idx = col("工单编号")  # None 表示资管型模板

    # 载体列：表头优先，否则按值扫描
    carrier_idx = col("工单载体", "EAM")
    if carrier_idx is None:
        carrier_idx = _detect_carrier_col(rows[hdr_idx + 1:])

    title_idx = col("工单名称", "工单内容", "详细措施")
    prio_idx = col("优先级")
    plan_idx = col("计划完成时间", "计划完成", "计划时间", "计划月份")  # 结束 → deadline
    start_idx = col("计划开始时间", "计划开始")  # 开始 → planned_start
    person_idx = col("负责角色", "责任人")
    action_idx = col("做什么事")
    accept_idx = col("交付物", "验收")
    target_idx = col("预期效果", "对目标的价值", "预计带来的效果")
    reason_ids = [i for i, h in enumerate(header) if any(k in h for k in ("根因", "问题", "拆解", "类别"))]

    out: list[dict] = []
    for row in rows[hdr_idx + 1:]:
        vals = [str(c).strip() if c is not None else "" for c in row]
        if not any(vals):
            continue

        def g(i):
            return vals[i] if i is not None and i < len(vals) else ""

        code = g(wo_code_idx) if wo_code_idx is not None else ""
        title_raw = g(title_idx)
        if wo_code_idx is not None:
            if not code.startswith("WO-"):
                continue
        else:
            if not title_raw:
                continue  # 资管型：措施空则跳过（续行/空行）

        reason = "；".join(x for x in (g(i) for i in reason_ids if i is not None and i < len(vals))
                           if x and x not in ("—", "-"))
        out.append({
            "code": code,
            "title": title_raw,
            "action": g(action_idx) or title_raw,
            "priority": g(prio_idx),
            "reason": reason,
            "target": g(target_idx),
            "plan": g(plan_idx),
            "start": g(start_idx),
            "person": g(person_idx),
            "accept": g(accept_idx),
            "carrier": g(carrier_idx),
        })
    return out


def _match_project(filename: str, projects: list[Project]) -> Project | None:
    """按文件名匹配项目：项目简称是文件名的子串即命中（最长匹配优先）。"""
    hits = [p for p in projects if p.name and p.name in filename]
    return max(hits, key=lambda p: len(p.name)) if hits else None


def import_drive_workorder_versions() -> dict:
    """一键导入钉盘「工单版」：搜索→下载→解析→导入（按 项目+标题 去重）。"""
    files = find_workorder_versions()
    if not files:
        return {"imported": 0, "skipped_file": 0, "errors": ["钉盘未找到「工单版」文件"]}

    projects = _load_projects()
    db = SessionLocal()
    users = {u.name: u for u in db.query(User).all()}
    imported = 0
    skipped_file = 0
    errors: list[str] = []
    try:
        for f in files:
            project = _match_project(f["name"], projects)
            if not project:
                skipped_file += 1
                errors.append(f"文件名匹配不到项目: {f['name']}")
                continue
            try:
                path = _download(f["fileId"])
                if path.is_dir():
                    skipped_file += 1
                    errors.append(f"下载失败/无xlsx: {f['name']}")
                    continue
                wos = _parse_sheet(path)
            except Exception as e:
                skipped_file += 1
                errors.append(f"解析失败 {f['name']}: {e}")
                continue

            # 只导入「工单载体 = 非EAM」的项；无该列的（如精简「工单版」）拿不到标记，整表跳过
            if wos and not any(w.get("carrier") for w in wos):
                skipped_file += 1
                errors.append(f"无「工单载体」列，跳过: {f['name']}")
                continue
            wos = [w for w in wos if (w.get("carrier") or "").strip() == "非EAM"]

            for w in wos:
                title = (f"{w['code']} {w['title']}".strip() if w.get("code") else w["title"])[:256]
                # 去重：同项目同来源同标题已存在则跳过
                dup = db.query(WorkOrder).filter(
                    WorkOrder.title == title,
                    WorkOrder.project_id == project.id,
                    WorkOrder.source_code == "plan",
                ).first()
                if dup:
                    continue
                reason = w["reason"]
                if w.get("target"):
                    reason = f"{reason}\n【预期】{w['target']}".strip()
                action = w["action"]
                if w.get("accept"):
                    action = f"{action}\n【验收】{w['accept']}"
                code = next_work_order_code(db)
                person_user = users.get((w.get("person") or "").strip())
                wo = WorkOrder(
                    code=code, title=title, reason=reason or None, action=action or title,
                    project_id=project.id,
                    person_id=person_user.id if person_user else None,
                    source_code="plan", status="pending", priority=_map_priority(w["priority"]),
                    region=project.region,
                    created_date=date.today(),
                    deadline=_parse_deadline(w["plan"]),
                    planned_start_date=_parse_deadline(w.get("start")),
                )
                db.add(wo)
                db.flush()
                note = f"年度计划工单导入(钉盘)·原编号{w['code']}"
                if not person_user and w.get("person"):
                    note += f"·责任人待确认({w['person']})"
                db.add(StatusLog(work_order_id=wo.id, from_status=None, to_status="pending", note=note))
                imported += 1
        db.commit()
    finally:
        db.close()
    return {"imported": imported, "skipped_file": skipped_file, "errors": errors, "files": len(files)}


def _load_projects() -> list[Project]:
    db = SessionLocal()
    try:
        return db.query(Project).all()
    finally:
        db.close()