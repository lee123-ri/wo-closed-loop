"""导入接口：听记解析 + 表格批量导入"""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security_middleware import limiter

from app.core.database import get_db
from app.models import Project, User, WorkOrder, WorkOrderTypeKB, StatusLog
from app.services.llm_service import parse_minutes
from app.services.priority_service import match_priority
from datetime import date, timedelta

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


def HTTPError(msg):  # 兼容 helper
    return HTTPException(400, msg)
