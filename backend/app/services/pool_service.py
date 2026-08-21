"""数据池服务：导入 → 生成工单 → 回填 → AI表格同步"""
import csv
import io
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import DataPoolItem, Project, RegionPMO, User, WorkOrder, WorkOrderTypeKB, StatusLog
from app.services.priority_service import normalize_priority
from app.services.roles import resolve_role_user_id


# ── 工具函数 ──────────────────────────────────────────────

def _extract_planned_start(item: DataPoolItem) -> date | None:
    """从数据池原始数据中提取计划开始时间"""
    if not item.raw_data:
        return None

    # 1. 先尝试匹配已知字段名（中文/英文）
    for key in ("计划开始时间", "计划开始", "开始时间", "start_date",
                "planned_start_date", "开始日期", "计划开始日期", "计划时间"):
        val = item.raw_data.get(key)
        if val:
            d = _parse_date(val)
            if d:
                return d

    # 2. 扫描所有 raw_data 值，找第一个日期，且不是 deadline
    for key, val in item.raw_data.items():
        if val and isinstance(val, str):
            d = _parse_date(val)
            if d and d != item.deadline:
                return d

    return None


def _parse_date(val: any) -> date | None:
    """尝试解析日期字符串"""
    if isinstance(val, (datetime, date)):
        return val.date() if isinstance(val, datetime) else val
    if isinstance(val, str):
        val = val.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return None


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
    "priority": ("priority", "优先级", "优先"),
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
    # priority 归一化为 P1/P2/P3（支持 "P1"/"1"/"p1"/"高" 等写法）
    out["priority"] = normalize_priority(out.get("priority"))
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
    # 区域 → PMO 映射（用于异常指标默认责任人）
    region_pmo_map: dict[str, User] = {}
    for rpmo in db.query(RegionPMO).all():
        user = db.get(User, rpmo.user_id)
        if user:
            region_pmo_map[rpmo.region] = user
    # 默认工单类型
    default_type = db.query(WorkOrderTypeKB).order_by(WorkOrderTypeKB.sort_order).first()
    # 默认审批人：优先按角色解析（后台可改人名），兜底用类型缓存的 person id
    default_approver_id = None
    if default_type:
        default_approver_id = resolve_role_user_id(db, default_type.default_approver_role) or default_type.default_approver_id

    for item in items:
        try:
            # 匹配项目
            project = _match_project(item.project_name, projects)

            # 匹配责任人
            # 异常指标类：优先按项目区域查找区域PMO
            person = None
            if item.pool_type == "anomaly" and project and project.region:
                person = region_pmo_map.get(project.region)
            # 如果区域PMO不存在，或非异常类：按姓名匹配
            if not person and item.person_name:
                person = _match_person(item.person_name, users)

            # 优先级按来源规则（业务规则 2026-08-20）：
            #   异常指标(anomaly) → P1；计划类(plan) → 同步年度运营计划自带优先级，缺失兜底 P2
            if item.pool_type == "anomaly":
                priority = "P1"
            else:
                priority = normalize_priority(item.priority) or "P2"

            # 生成 code（max+1，避免删除导致编号空洞撞号）
            code = _next_code(db)

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
                approver_id=default_approver_id,
                type_id=default_type.id if default_type else None,
                source_code=source_code,
                region=project.region if project and project.region else None,
                priority=priority,
                status="dispatched" if item.pool_type == "plan" else "pending",
                created_date=date.today(),
                planned_start_date=_extract_planned_start(item),
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
                        new_wo_person_name: str | None = None,
                        accept_judgment: bool | None = None,
                        override_judgment: bool = False) -> dict:
    """工单回填：责任人填写原因+措施

    1. 写入 WorkOrder 的 backfill 字段
    2. 回传给 DataPoolItem（如有 parent_pool_id）
    3. 如果来源是 alert 且 trigger_new_wo → 调判断Agent审核
    4. 根据判断结果创建/不创建措施工单
    """
    from app.services.judgment_agent import record_degradation

    wo = db.get(WorkOrder, wo_id)
    if not wo:
        raise ValueError("工单不存在")

    wo.backfill_status = "filled"
    if reason:
        wo.backfill_reason = reason
    if action:
        wo.backfill_action = action
    wo.backfilled_at = datetime.now()

    # 保存PMO建议的新工单参数
    if trigger_new_wo:
        wo.triggered_wo_title = new_wo_title
        wo.triggered_wo_deadline = new_wo_deadline
        wo.triggered_wo_person_name = new_wo_person_name

    # 回传数据池记录
    pool = None
    if wo.parent_pool_id:
        pool = db.get(DataPoolItem, wo.parent_pool_id)
        if pool:
            pool.backfill_reason = reason
            pool.backfill_action = action
            pool.backfilled_at = wo.backfilled_at

    # ── 判断Agent 流程（离线模式：Agent 结果通过导入接口预先回填） ──
    judgment = None
    triggered_wo_id = None

    if trigger_new_wo:
        # 直接创建工单B（Agent结果已通过 import-judgment 接口预先回填）
        triggered_wo_id = _create_triggered_wo(
            db, wo, new_wo_title, new_wo_deadline, new_wo_person_name
        )

        # 如果已有Agent判断结果，补充到工单B的action中
        if wo.judgment_result:
            tasks = wo.judgment_result.get("tasks", [])
            if isinstance(tasks, list) and len(tasks) > 1:
                triggered = db.get(WorkOrder, triggered_wo_id)
                if triggered:
                    extra = "\n\n【Agent全部建议措施】\n" + "\n".join(
                        f"{i+1}. {t.get('title', str(t))} → {t.get('responsible', '?')}"
                        for i, t in enumerate(tasks)
                    )
                    triggered.action = (triggered.action or "") + extra

        # 更新判断状态
        wo.judgment_status = "approved"
        db.add(StatusLog(work_order_id=wo.id, from_status=wo.status,
                        to_status=wo.status, note="回填提交·措施工单已生成"))

    db.commit()
    db.refresh(wo)

    result = {
        "work_order_id": wo.id,
        "reason": wo.backfill_reason,
        "action": wo.backfill_action,
        "triggered_wo_id": triggered_wo_id,
        "backfilled_at": wo.backfilled_at,
    }
    if judgment:
        result["verdict"] = judgment["verdict"]
        result["judgment_reasoning"] = judgment.get("reasoning", "")
        result["judgment_suggestions"] = judgment.get("suggestions")
        result["judgment_confidence"] = judgment.get("confidence")
    return result


def _create_triggered_wo(
    db: Session,
    parent_wo: WorkOrder,
    title: str | None,
    deadline_val: date | None,
    person_name: str | None,
    priority: str | None = None,
    action_adjustment: str | None = None,
    task_reason: str | None = None,
    task_action: str | None = None,
    type_id: int | None = None,
) -> int:
    """创建措施工单B，返回新工单ID"""
    final_title = (title or f"措施执行：{parent_wo.title[:200]}")[:256]
    new_code = _next_code(db)
    person = _match_person(
        person_name or "",
        {u.name: u for u in db.query(User).all()}
    ) if person_name else None

    # 触发原因：优先用任务级，否则继承父工单的回填原因
    reason_text = task_reason or f"由工单 {parent_wo.code} 触发"
    if parent_wo.backfill_reason and not task_reason:
        reason_text = f"由 {parent_wo.code} 触发：{parent_wo.backfill_reason}"

    # 行动要求：优先用任务级，否则继承父工单的回填措施
    action_text = task_action or parent_wo.backfill_action or final_title
    if action_adjustment:
        action_text = f"{action_text}\n\n【Agent建议补充】{action_adjustment}"

    new_wo = WorkOrder(
        code=new_code,
        title=final_title,
        reason=reason_text,
        action=action_text,
        project_id=parent_wo.project_id,
        person_id=person.id if person else parent_wo.person_id,
        approver_id=parent_wo.approver_id,  # 继承审批人
        type_id=type_id if type_id else parent_wo.type_id,  # 措施工单类型（人工选择，未选则继承父单）
        region=parent_wo.region,            # 继承区域
        source_code="alert",
        priority=priority or parent_wo.priority,
        status="dispatched",                # PMO已审核，直接派发
        created_date=date.today(),
        deadline=deadline_val or parent_wo.deadline,
    )
    db.add(new_wo)
    db.flush()
    db.add(StatusLog(work_order_id=new_wo.id, from_status=None, to_status="dispatched",
                     note=f"由工单 {parent_wo.code} 判定生成·PMO已审核直接派发"))
    parent_wo.triggered_wo_id = new_wo.id
    return new_wo.id


def _next_code(db: Session) -> str:
    from app.services.workorder_code import next_work_order_code
    return next_work_order_code(db)


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