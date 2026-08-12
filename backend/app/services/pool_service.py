"""数据池服务：导入 → 生成工单 → 回填 → AI表格同步"""
import csv
import io
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import DataPoolItem, Project, User, WorkOrder, WorkOrderTypeKB, StatusLog
from app.services.priority_service import match_priority


# ── 导入 ──────────────────────────────────────────────

def parse_csv(content: str, pool_type: str, source_system: str = "excel") -> dict:
    """解析 CSV 内容为数据池记录，返回 {imported, skipped, errors}

    通用字段映射（支持中文/英文列名）:
      title/标题, project/项目/场站, person/责任人, deadline/截止日期/截止时间,
      description/描述/原因/触发原因, metric_type/指标类型, metric_value/指标值,
      threshold/阈值, deviation_pct/偏离
    """
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return {"imported": 0, "skipped": 0, "errors": ["CSV 无数据行"]}

    imported = 0
    skipped = 0
    errors: list[str] = []
    db = SessionLocal()
    try:
        for i, row in enumerate(rows, 2):
            try:
                item = _row_to_item(row, pool_type, source_system)
                if not item["title"]:
                    skipped += 1
                    errors.append(f"第{i}行：缺少标题")
                    continue
                db.add(DataPoolItem(**item))
                imported += 1
            except Exception as e:
                skipped += 1
                errors.append(f"第{i}行：{e}")
        db.commit()
    finally:
        db.close()
    return {"imported": imported, "skipped": skipped, "errors": errors}


_COMMON_COL = {
    "title": ("title", "标题"),
    "project_name": ("project_name", "project", "项目", "场站", "电站", "项目名称"),
    "person_name": ("person_name", "person", "责任人", "负责人", "人员"),
    "deadline": ("deadline", "截止日期", "截止时间", "完成时间", "完成日期"),
    "description": ("description", "描述", "原因", "触发原因", "异常描述", "备注"),
    "metric_type": ("metric_type", "指标类型", "指标"),
    "metric_value": ("metric_value", "指标值", "数值", "值"),
    "threshold": ("threshold", "阈值", "标准值", "标准"),
    "deviation_pct": ("deviation_pct", "偏离", "偏离%", "偏差"),
}


def _row_to_item(row: dict[str, str], pool_type: str, source_system: str) -> dict:
    """将一行 CSV 映射为 DataPoolItem 字段"""
    lower = {k.lower(): v for k, v in row.items()}
    out: dict[str, Any] = {
        "pool_type": pool_type,
        "source_system": source_system,
        "raw_data": row,
    }
    for field, *aliases in _COMMON_COL.values():
        out[field] = None
        for alias in aliases:
            if alias in lower and lower[alias].strip():
                out[field] = lower[alias].strip()
                break
    # deadline 解析
    dl = out.get("deadline")
    if dl and isinstance(dl, str):
        try:
            out["deadline"] = date.fromisoformat(dl)
        except ValueError:
            out["deadline"] = None
    # metric_value / threshold 数值化
    for num_field in ("metric_value", "threshold", "deviation_pct"):
        v = out.get(num_field)
        if v is not None:
            try:
                out[num_field] = float(str(v).replace("%", "").strip())
            except (ValueError, TypeError):
                out[num_field] = None
    return out


# ── 工单生成 ──────────────────────────────────────────

def generate_from_pool(db: Session, pool_ids: list[int]) -> dict:
    """从数据池批量生成工单

    1. 查询 pool items（status=pending）
    2. 匹配项目名 → Project
    3. 匹配责任人 → User
    4. 应用优先级规则 → priority
    5. 创建 WorkOrder + StatusLog
    6. 更新 pool item status=generated, work_order_id=wo.id
    """
    items = (
        db.query(DataPoolItem)
        .filter(DataPoolItem.id.in_(pool_ids), DataPoolItem.status == "pending")
        .all()
    )
    if not items:
        return {"generated": 0, "skipped": 0, "errors": ["没有待生成的记录"], "work_order_ids": []}

    generated = 0
    skipped = 0
    errors: list[str] = []
    work_order_ids: list[int] = []

    # 预加载映射
    projects = {p.name: p for p in db.query(Project).all()}
    users = {u.name: u for u in db.query(User).all()}
    # 默认工单类型
    default_type = db.query(WorkOrderTypeKB).order_by(WorkOrderTypeKB.sort_order).first()

    for item in items:
        try:
            # 匹配项目
            project = _match_project(item.project_name, projects)

            # 匹配责任人
            person = None
            if item.person_name:
                person = _match_person(item.person_name, users)

            priority = match_priority(db, f"{item.title} {item.description or ''}", "")

            # 生成 code
            year = date.today().year
            cnt = db.query(WorkOrder).filter(WorkOrder.code.like(f"RW-{year}-%")).count()
            code = f"RW-{year}-{cnt + 1:04d}"

            # 来源 code
            source_map = {"plan": "plan", "anomaly": "alert", "aitable": "meeting", "excel": "manual"}
            source_code = source_map.get(item.source_system, "manual")

            wo = WorkOrder(
                code=code,
                title=item.title[:256],
                reason=item.description or item.title,
                action=item.title,
                project_id=project.id if project else None,
                person_id=person.id if person else None,
                approver_id=default_type.default_approver_id if default_type else None,
                type_id=default_type.id if default_type else None,
                source_code=source_code,
                priority=priority,
                status="dispatched" if item.pool_type == "plan" else "pending",
                created_date=date.today(),
                deadline=item.deadline,
                parent_pool_id=item.id,
            )
            db.add(wo)
            db.flush()
            status_note = "数据池批量生成·直接派发" if item.pool_type == "plan" else "数据池自动生成·待审批"
            db.add(StatusLog(
                work_order_id=wo.id, from_status=None, to_status=wo.status,
                note=f"{status_note} ({item.pool_type}/{item.source_system})",
            ))

            item.status = "generated"
            item.work_order_id = wo.id
            generated += 1
            work_order_ids.append(wo.id)
        except Exception as e:
            skipped += 1
            errors.append(f"记录 {item.id} ({item.title[:30]}): {e}")

    db.commit()
    return {"generated": generated, "skipped": skipped, "errors": errors, "work_order_ids": work_order_ids}


def _match_project(name: str | None, projects: dict[str, Project]) -> Project | None:
    """模糊匹配项目名"""
    if not name:
        return None
    # 精确匹配
    if name in projects:
        return projects[name]
    # 包含匹配
    for pname, p in projects.items():
        if name in pname or pname in name:
            return p
    # 代码匹配
    for pname, p in projects.items():
        if p.code and name.upper() == p.code.upper():
            return p
    return None


def _match_person(name: str, users: dict[str, User]) -> User | None:
    """模糊匹配责任人"""
    if name in users:
        return users[name]
    # 姓匹配
    for uname, u in users.items():
        if name in uname or uname in name:
            return u
    return None


# ── 回填 ──────────────────────────────────────────────

def backfill_work_order(db: Session, wo_id: int, reason: str | None, action: str | None,
                        trigger_new_wo: bool = False,
                        new_wo_title: str | None = None,
                        new_wo_deadline: date | None = None,
                        new_wo_person_name: str | None = None) -> dict:
    """工单回填：责任人填写原因+措施

    1. 写入 WorkOrder 的 backfill 字段
    2. 回传给 DataPoolItem（如有 parent_pool_id）
    3. 可选：触发新工单
    """
    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise ValueError("工单不存在")

    wo.backfill_status = "filled"
    if reason:
        wo.backfill_reason = reason
    if action:
        wo.backfill_action = action
    wo.backfilled_at = datetime.now()

    # 回传数据池记录
    triggered_wo_id = None
    if wo.parent_pool_id:
        pool = db.get(DataPoolItem, wo.parent_pool_id)
        if pool:
            pool.backfill_reason = reason
            pool.backfill_action = action
            pool.backfilled_at = wo.backfilled_at

    # 触发新工单
    if trigger_new_wo:
        title = new_wo_title or f"措施执行：{wo.title[:200]}"
        new_code = _next_code(db)
        person = _match_person(new_wo_person_name or "", {u.name: u for u in db.query(User).all()}) if new_wo_person_name else None
        new_wo = WorkOrder(
            code=new_code,
            title=title[:256],
            reason=f"回填触发：{wo.code} {wo.title}",
            action=title,
            project_id=wo.project_id,
            person_id=person.id if person else wo.person_id,
            source_code=wo.source_code,
            priority=wo.priority,
            status="pending",
            created_date=date.today(),
            deadline=new_wo_deadline or wo.deadline,
        )
        db.add(new_wo)
        db.flush()
        db.add(StatusLog(work_order_id=new_wo.id, from_status=None, to_status="pending",
                         note=f"由工单 {wo.code} 回填触发"))
        wo.triggered_wo_id = new_wo.id
        triggered_wo_id = new_wo.id

    db.commit()
    db.refresh(wo)
    return {
        "work_order_id": wo.id,
        "reason": wo.backfill_reason,
        "action": wo.backfill_action,
        "triggered_wo_id": triggered_wo_id,
        "backfilled_at": wo.backfilled_at,
    }


def _next_code(db: Session) -> str:
    year = date.today().year
    cnt = db.query(WorkOrder).filter(WorkOrder.code.like(f"RW-{year}-%")).count()
    return f"RW-{year}-{cnt + 1:04d}"


# ── AI表格同步 ─────────────────────────────────────────

def sync_from_aitable(db: Session, base_id: str, table_id: str,
                      pool_type: str = "anomaly") -> dict:
    """从钉钉 AI 表格拉取数据写入数据池

    调用 DingTalk AITable API 拉取记录，映射为 DataPoolItem。
    """
    try:
        from app.services.aitable import get_aitable_records
        records = get_aitable_records(base_id, table_id)
    except ImportError:
        return {"imported": 0, "errors": ["aitable 服务未实现"]}
    except Exception as e:
        return {"imported": 0, "errors": [f"AI表格读取失败: {e}"]}

    if not records:
        return {"imported": 0, "errors": ["AI表格返回空数据"]}

    imported = 0
    errors: list[str] = []
    for i, rec in enumerate(records):
        try:
            fields = rec.get("fields", {}) if isinstance(rec, dict) else {}
            item = DataPoolItem(
                pool_type=pool_type,
                source_system="aitable",
                source_ref=str(rec.get("recordId", "") if isinstance(rec, dict) else ""),
                title=str(fields.get("title", fields.get("事项", fields.get("异常描述", "")))),
                project_name=str(fields.get("project", fields.get("场站", "")) or None),
                person_name=str(fields.get("person", fields.get("责任人", "")) or None),
                description=str(fields.get("description", fields.get("描述", "")) or None),
                raw_data=fields,
            )
            if not item.title:
                errors.append(f"第{i+1}条：缺少标题")
                continue
            # deadline
            dl = fields.get("deadline", fields.get("截止日期"))
            if dl:
                try:
                    item.deadline = date.fromisoformat(str(dl))
                except (ValueError, TypeError):
                    pass
            db.add(item)
            imported += 1
        except Exception as e:
            errors.append(f"第{i+1}条：{e}")
    if imported:
        db.commit()
    return {"imported": imported, "errors": errors}


def backfill_to_aitable(db: Session, pool_item: DataPoolItem) -> bool:
    """将回填数据写回 AI 表格

    通过 AI 表格 API 更新原始记录，加入原因和措施字段。
    """
    if not pool_item.source_ref:
        return False
    try:
        from app.services.aitable import update_aitable_record
        update_aitable_record(
            source_ref=pool_item.source_ref,
            fields={
                "backfill_reason": pool_item.backfill_reason or "",
                "backfill_action": pool_item.backfill_action or "",
                "backfill_status": "filled",
                "backfilled_at": pool_item.backfilled_at.isoformat() if pool_item.backfilled_at else "",
            },
        )
        return True
    except Exception as e:
        print(f"[pool] 回写AI表格失败: {e}")
        return False