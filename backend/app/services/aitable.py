"""钉钉 AI 表格同步服务 — 多表合一"""
import re
from datetime import date
from app.core.database import SessionLocal
from app.models import DataPoolItem, Project, User, WorkOrder
from app.services.cell_utils import cell_to_text
from app.services.dws_client import run_dws
from app.services.metric_types import classify_metric_type
from app.services.priority_service import normalize_priority
from app.services.region_map import normalize_region

# ── 数据源 ────────────────────────────────────────────
ANOMALY_BASE = "OG9lyrgJPzMw9B5jSvpyvdQLWzN67Mw4"   # 数据池-异常指标
ANOMALY_TABLE = "j5hkt042bpz1m88o46iup"              # 汇总表
DUAL_RULE_TABLE = "XsYShRm"                          # 双细则异常（已工单形态，直导工单）

MAP_BASE = "1zknDm0WRaNwg5KkI0BwAMRy8BQEx5rG"       # 数据池-数仓
MAP_TABLE = "Dzp793M"                                 # 0映射表

PLAN_BASE = "bva6QBXJwanjQ4B6IMlleblnWn4qY5Pr"       # 数据池-计划
PLAN_TABLE = "bOywzmP"                                 # 异常原因表


def _get_records(base_id: str, table_id: str) -> list[dict]:
    data = run_dws("aitable", "record", "query", "--base-id", base_id, "--table-id", table_id, "--all", "--page-limit", "0")
    result = data.get("data", data.get("result", data))
    return result.get("records", result.get("items", []))


def _cv(cells: dict, fid: str) -> str:
    """提取单元格值（任意字段类型 → 文本，含 filterUp 查找引用）"""
    return cell_to_text(cells.get(fid))


def _first_name(cells: dict, fid: str) -> str:
    """filterUp「user」多值字段 → 第一个责任人姓名。

    双细则表的「责任人」值形如 [[{name,uid}],[{name,uid}]]（同一人可能重复出现），
    cell_to_text 会拼接成「雷江涛, 雷江涛」，这里取第一个去重结果。
    """
    s = cell_to_text(cells.get(fid))
    for part in s.split(","):
        name = part.strip()
        if name:
            return name
    return ""


def _build_raw(cells: dict, field_map: dict) -> dict:
    """从 AI 表格 cells 中提取所有字段值，存入 raw_data。
    field_map: {field_id: 中文字段名}
    返回包含所有可读字段名的 dict，供后续 _extract_planned_start 等使用。
    """
    raw = {}
    for fid, val in cells.items():
        label = field_map.get(fid, fid)
        if isinstance(val, dict):
            raw[label] = val.get("name", val.get("text", str(val)))
        elif isinstance(val, list) and val:
            raw[label] = ", ".join(
                v.get("name", str(v)) if isinstance(v, dict) else str(v) for v in val
            )
        else:
            raw[label] = str(val) if val is not None else ""
    return raw


# ── 1. 映射表 → 本地项目/人员缓存 ──────────────────────

def sync_project_map() -> dict:
    """从数仓.0映射表拉取项目→人员映射"""
    try:
        records = _get_records(MAP_BASE, MAP_TABLE)
    except Exception as e:
        print(f"[sync] 映射表失败: {e}")
        return {}
    mapping = {}
    for r in records:
        c = r.get("cells", {})
        proj = _cv(c, "xOTtpZc")      # 项目简称
        eam = _cv(c, "TMaSENb")        # EAM名称
        oms = _cv(c, "i3okDTQ")        # OMS名称
        pi = _cv(c, "4avsLpq")         # PowerInsight名称
        person = _cv(c, "IFHB40F")      # 场站第一负责人
        province = _cv(c, "v6ZTRXw")    # 省份
        region = normalize_region(province)  # 省份 → 大区（识别不了为 None）
        if proj:
            mapping[proj] = {"person": person, "eam": eam, "oms": oms, "pi": pi,
                             "province": province, "region": region}
        if eam and eam not in mapping:
            mapping[eam] = {"person": person, "project": proj, "province": province, "region": region}
    return mapping


# ── 2. 异常指标 → 信息搜集工单 ─────────────────────────

_MONTH_RE = re.compile(r"^\s*(\d{1,2})\s*月\s*$")


def _keep_month(month: str) -> bool:
    """只保留「7 月及以后」的异常；1-6 月、空、『25年分析』等未标注的不进系统（2026-09-10 用户拍板）。"""
    m = _MONTH_RE.match(month or "")
    return bool(m) and int(m.group(1)) >= 7


def sync_anomaly_to_pool(full: bool = False) -> dict:
    """从异常指标.汇总表 → 数据池 (pool_type=anomaly)

    每条记录是一个异常事件，生成"信息搜集工单"，
    责任人回填原因+措施后，可触发"动作工单"。
    """
    try:
        records = _get_records(ANOMALY_BASE, ANOMALY_TABLE)
    except Exception as e:
        return {"synced": 0, "errors": [f"dws: {e}"]}

    db = SessionLocal()
    existing_refs = set()
    if not full:
        existing = db.query(DataPoolItem.source_ref).filter(
            DataPoolItem.source_system.in_(("anomaly", "anomaly_baseline")), DataPoolItem.source_ref.isnot(None)
        ).all()
        existing_refs = {r[0] for r in existing}

    synced = 0; skipped_early = 0; errors = []
    for r in records:
        rid = r.get("recordId", "")
        c = r.get("cells", {})
        if not full and rid in existing_refs: continue
        try:
            proj = _cv(c, "06h8ukzbt5k6lit2wupf2")           # OA项目名称（singleSelect）
            person = _cv(c, "v6mn5bqeigdt6xmm4a45b")         # 整改人（filterUp 查找引用）
            pmo = _cv(c, "1kgnhr6fqota0ct19aqn6")            # PMO（singleSelect；2026-09-11 上游改表后此字段由「整改人」变为 PMO）
            anomaly_type = _cv(c, "dudwqcjgwobfozvuhgu7l")   # 异常指标（singleSelect）
            month = _cv(c, "6xwktuomtdhlqqd3iqh3q")          # 异常月份（singleSelect）
            region = _cv(c, "rmnmea3m114npk2s537em")         # 区域（singleSelect，区域中心/交付中心/子公司）
            reason_category = _cv(c, "xyflaonxfsr57nfnt5df4")  # 原因分类（filterUp 多选）
            # 只进 7 月及以后；之前/未标注（空、『25年分析』等）跳过
            if not _keep_month(month):
                skipped_early += 1
                continue
            title = f"{proj}-{anomaly_type}"[:512] if proj else anomaly_type[:512]
            # 全量存储原始 cell 数据（任意字段类型 → 文本），供后续提取计划开始时间等字段
            raw = {k: cell_to_text(c.get(k)) for k in c}
            raw.update({
                "anomaly_type": anomaly_type,
                "month": month,
                "region": region,
                "pmo": pmo,
                "reason_category": reason_category,
            })
            # 异常指标大类（发电量/限电量/双细则/可靠性/信息化/应签未签/成本/满意度）
            metric_type = classify_metric_type(anomaly_type)
            db.add(DataPoolItem(
                pool_type="anomaly", source_system="anomaly", source_ref=rid,
                title=title, project_name=proj, person_name=person,
                description=f"异常月份: {month} | 区域: {region}",
                status="pending",
                metric_type=metric_type,
                raw_data=raw,
            ))
            synced += 1
        except Exception as e:
            errors.append(f"{rid}: {e}")
    db.commit(); db.close()
    return {"synced": synced, "skipped_early": skipped_early, "errors": errors, "total": len(records)}


# ── 3. 异常原因 → 非EAM工单 ──────────────────────────

def sync_non_eam_to_pool(full: bool = False) -> dict:
    """从异常原因表 → 数据池 (pool_type=plan)

    这些是"应推工单但未推"的非EAM工单。
    """
    try:
        records = _get_records(PLAN_BASE, PLAN_TABLE)
    except Exception as e:
        return {"synced": 0, "errors": [f"dws: {e}"]}

    db = SessionLocal()
    existing_refs = set()
    if not full:
        existing = db.query(DataPoolItem.source_ref).filter(
            DataPoolItem.source_system == "non_eam", DataPoolItem.source_ref.isnot(None)
        ).all()
        existing_refs = {r[0] for r in existing}

    synced = 0; errors = []
    for r in records:
        rid = r.get("recordId", "")
        c = r.get("cells", {})
        if not full and rid in existing_refs: continue
        try:
            anomaly = _cv(c, "UjHVcMP")       # 异常甄别
            reason = _cv(c, "ivATb5i")         # 待异常原因反馈
            region = _cv(c, "iR5P7hE")          # 区域
            proj = _cv(c, "mAFIHjj")            # OA项目
            person = _cv(c, "Mp4xZHB")          # 项目第一负责人
            title = f"{proj}-{anomaly}"[:512] if proj else anomaly[:512]
            # 全量存储原始 cell 数据，供后续提取计划开始时间等字段
            raw = {k: _cv(c, k) for k in c}
            raw.update({"anomaly": anomaly, "reason": reason, "region": region})
            db.add(DataPoolItem(
                pool_type="plan", source_system="non_eam", source_ref=rid,
                title=title, project_name=proj, person_name=person,
                description=f"{anomaly}: {reason}"[:1000],
                status="pending",
                raw_data=raw,
            ))
            synced += 1
        except Exception as e:
            errors.append(f"{rid}: {e}")
    db.commit(); db.close()
    return {"synced": synced, "errors": errors, "total": len(records)}


# ── 4. 双细则异常 → 直接生成工单 ──────────────────────

def sync_dual_rule_to_workorders(full: bool = False) -> dict:
    """从「双细则异常」表直导工单（不经过数据池）。

    上游把双细则考核单独拆了子表（XsYShRm），且这张表自带工单形态——
    有 SXZ 编号、场站、区域、异常指标、优先级、责任人、工单状态（待派单）、
    原因措施、验证结论等。这里 1:1 落成平台 WorkOrder：优先级原样保留（P0→P1），
    责任人走双细则大类默认责任人（config_definitions category=anomaly_type
    code=dual_rule → 默认徐林杰），配不到人再退回表里填报责任人。
    双细则表自带「场站填报原因及措施」=已回填 → 直接置 status=judging +
    alert_phase=confirming，进入 alert 五阶段①「分析确认」（有「填写措施工单」按钮）。
    幂等：按 SXZ 编号写入 client_request_id（sxz-前缀），已存在则跳过。
    """
    try:
        records = _get_records(ANOMALY_BASE, DUAL_RULE_TABLE)
    except Exception as e:
        return {"synced": 0, "errors": [f"dws: {e}"]}

    db = SessionLocal()
    from app.services.maintenance import is_paused
    if is_paused(db):
        db.close()
        return {"synced": 0, "errors": ["系统暂停发单，跳过双细则直导"], "total": len(records), "paused": True}
    # 幂等：始终预加载已有 SXZ 编号，增量/全量都跳过已存在。
    # 原实现只在 full=False 时加载，full=True 会重复 INSERT 撞 work_orders_client_request_id_key 唯一约束。
    rows = db.query(WorkOrder.client_request_id).filter(
        WorkOrder.client_request_id.like("sxz-%")).all()
    existing: set[str] = {r[0] for r in rows if r[0]}
    existing.update(r[0] for r in db.query(DataPoolItem.source_ref).filter(
        DataPoolItem.source_system == "dual_rule_baseline", DataPoolItem.source_ref.isnot(None)).all())

    # 项目/人员/编号预加载（复用 generate_from_pool 同款匹配逻辑）
    from app.models import ConfigDefinition
    projects = {p.name: p for p in db.query(Project).all()}
    users = {u.name: u for u in db.query(User).all()}
    # 双细则大类默认责任人（config category=work_order_type, code=dual_rule → 徐林杰）
    default_person_name = ""
    for cd in db.query(ConfigDefinition).filter_by(category="work_order_type", code="dual_rule").all():
        default_person_name = (cd.extra or {}).get("default_person_name") or ""
    from app.services.pool_service import _match_project, _match_person

    year = date.today().year
    seq = db.query(WorkOrder).filter(WorkOrder.code.like(f"RW-{year}-%")).count()

    synced = 0; errors: list[str] = []
    work_order_ids: list[int] = []
    for r in records:
        rid = r.get("recordId", "")
        c = r.get("cells", {})
        try:
            sxz = _cv(c, "n2dmwW8") or rid          # 异常工单编号 SXZ-xxx
            ccid = f"sxz-{sxz}"
            if ccid in existing:
                continue
            title = (_cv(c, "5o83YsJ") or f"双细则异常-{sxz}")[:256]
            proj_name = _cv(c, "GR6wzxe")            # 场站名称(OA)
            idx = _cv(c, "OMe1zkx")                  # 实际值(%)
            thr = _cv(c, "Jx1SwAb")                  # 标准阈值
            gap = _cv(c, "oa5Nf8a")                  # 差距(百分点)
            sev = _cv(c, "CjJ3IAZ")                  # 严重度 red/yellow/gray
            acc_days = _cv(c, "uZaBDxu")             # 累计异常日
            reason = _cv(c, "MeQwTQU") or _cv(c, "y2hiabP")   # 场站填报原因及措施 / 备注兜底
            note = _cv(c, "y2hiabP")                 # 备注/待核
            person_name = _first_name(c, "c9ouglA")  # 表里填报责任人（filterUp user，仅备注/兜底）
            prio_raw = _cv(c, "MfzDKTp")             # P0/P2
            priority = {"P0": "P1"}.get(prio_raw) or normalize_priority(prio_raw) or "P2"
            region = normalize_region(_cv(c, "JSvIxyO"))
            biz_raw = _cv(c, "jFO4J0Y")              # 业务日期
            try:
                biz_date = date.fromisoformat(biz_raw[:10])
            except Exception:
                biz_date = date.today()

            project = _match_project(proj_name, projects)
            # 工单责任人 = 双细则大类默认责任人（config → 徐林杰）；配置里配不到人再退回表里填报责任人
            person = _match_person(default_person_name, users) if default_person_name else None
            if not person and person_name:
                person = _match_person(person_name, users)

            # 行动要求：把指标数值/严重度/备注拼成可读摘要（不臆造 deadline，留空人工补）
            parts = []
            for label, val in (("实际值", idx), ("阈值", thr), ("差距", gap),
                               ("严重度", sev), ("累计异常", acc_days)):
                if val:
                    parts.append(f"{label} {val}{'%' if label in ('实际值', '差距') else ''}{'天' if label == '累计异常' else ''}")
            if note and note != reason:
                parts.append(f"备注 {note}")
            if person_name and person_name != default_person_name:
                parts.append(f"填报责任人 {person_name}")
            action = "｜".join(parts) or None

            seq += 1
            code = f"RW-{year}-{seq:04d}"
            wo = WorkOrder(
                code=code, client_request_id=ccid,
                title=title, reason=reason, action=action,
                project_id=project.id if project else None,
                person_id=person.id if person else None,
                source_code="dual_rule", metric_type="dual_rule",
                region=region, status="judging", priority=priority,
                # 双细则表自带场站填报原因+措施=已回填 → 直接进入 alert 五阶段①「分析确认」
                alert_phase="confirming",
                backfill_status="filled",
                backfill_reason=reason,
                backfill_action=note or None,
                created_date=biz_date,
            )
            db.add(wo)
            db.flush()
            from app.models import StatusLog
            db.add(StatusLog(
                work_order_id=wo.id, from_status=None, to_status=wo.status,
                note="双细则异常导入·已回填·进入分析确认",
            ))
            existing.add(ccid)
            work_order_ids.append(wo.id)
            synced += 1
        except Exception as e:
            errors.append(f"{rid}: {e}")
    db.commit(); db.close()
    return {"synced": synced, "errors": errors, "total": len(records), "work_order_ids": work_order_ids}


# ── 一键全量同步 ──────────────────────────────────────

def sync_all() -> dict:
    return {
        "anomaly": sync_anomaly_to_pool(full=True),
        "non_eam": sync_non_eam_to_pool(full=True),
        "map": sync_project_map(),
    }


def full_sync() -> dict:
    """一键同步全链路：AITable→数据池→生成工单 + 钉盘「工单版」xlsx→工单。"""
    from app.services.drive_workorder_import import import_drive_workorder_versions
    from app.services.pool_service import generate_from_pool

    # 1. AITable → 数据池
    a = sync_anomaly_to_pool(full=True)
    n = sync_non_eam_to_pool(full=True)
    sync_project_map()
    d = sync_dual_rule_to_workorders(full=True)   # 双细则异常 → 直导工单

    # 2. 数据池 → 工单
    db = SessionLocal()
    pool_generated = 0
    try:
        ids = [r[0] for r in db.query(DataPoolItem.id).filter(DataPoolItem.status == "pending").all()]
        if ids:
            pool_generated = generate_from_pool(db, ids).get("generated", 0)
    finally:
        db.close()

    # 3. 钉盘「工单版」→ 工单
    drive = import_drive_workorder_versions()

    return {
        "aitable": {"anomaly_synced": a.get("synced", 0), "non_eam_synced": n.get("synced", 0),
                    "dual_rule_synced": d.get("synced", 0)},
        "pool_generated": pool_generated,
        "drive_imported": drive.get("imported", 0),
        "drive_files": drive.get("files", 0),
        "errors": drive.get("errors", [])[:5],
    }


def run_anomaly_daily_sync() -> dict:
    """定时增量：异常指标表 → 数据池 → 原因工单（只落新增）。

    生产由 Celery beat 的 sync-anomaly-daily 触发；本地开发由 services/sync_poller.py
    的进程内轮询触发（一天一次）。增量幂等：已存在的 source_ref 跳过，故可重复调用。
    受 settings.anomaly_sync_start_date 约束：未到该日期直接 skip（用于先配好默认责任人再开跑）。
    """
    from app.core.config import get_settings
    start = get_settings().anomaly_sync_start_date
    if start and date.today() < start:
        return {"skipped": True, "reason": f"未到开始日期 {start.isoformat()}（今日 {date.today().isoformat()}）"}

    from app.services.pool_service import generate_from_pool

    result = sync_anomaly_to_pool(full=False)
    dual = sync_dual_rule_to_workorders(full=False)

    db = SessionLocal()
    generated = 0
    generate_errors: list = []
    anomaly_wo_ids: list[int] = []
    try:
        ids = [
            r[0] for r in db.query(DataPoolItem.id)
            .filter(DataPoolItem.pool_type == "anomaly", DataPoolItem.status == "pending")
            .all()
        ]
        if ids:
            out = generate_from_pool(db, ids)
            generated = out.get("generated", 0)
            generate_errors = out.get("errors", [])
            anomaly_wo_ids = out.get("work_order_ids", [])
    finally:
        db.close()

    return {
        "synced": result.get("synced", 0),
        "total": result.get("total", 0),
        # 新增异常只建立原因工单并路由到责任人列表；绝不在同步任务里
        # 创建措施工单、发 OA 或发送消息。措施必须经原因回填和人工确认后生成。
        "generated": generated,
        "reason_work_orders": len(anomaly_wo_ids) + len(dual.get("work_order_ids", [])),
        "dual_rule_synced": dual.get("synced", 0),
        "errors": (result.get("errors") or []) + (dual.get("errors") or []) + generate_errors,
    }


def sync_project_map_to_db() -> dict:
    """从数仓.0映射表同步项目到本地 projects 表（含区域=大区回填）。

    幂等要点：映射表同一项目会以「简称」和「EAM名」两个键出现，按项目名去重；
    项目 code 生成在「库内已有 + 本批新增」两个集合里查重，避免唯一约束冲突。
    """
    mapping = sync_project_map()
    if not mapping:
        return {"new_projects": 0, "region_updated": 0, "message": "无数据"}
    from app.services.project_codes import next_project_code
    db = SessionLocal()
    new_count = 0
    region_updated = 0
    try:
        batch_names: set[str] = set()
        for proj_name, info in mapping.items():
            project_name = info.get("project", proj_name)
            if not project_name or len(project_name) < 2 or project_name in batch_names:
                continue
            region = info.get("region", "")  # 大区
            existing = db.query(Project).filter(Project.name == project_name).first()
            if existing:
                # 已存在：回填/纠正区域为大区
                if region and existing.region != region:
                    existing.region = region
                    region_updated += 1
                batch_names.add(project_name)
                continue
            # 编码统一 PRJ-#### 自动分配（flush 让本批后续编号可见）
            db.add(Project(code=next_project_code(db), name=project_name, region=region))
            db.flush()
            batch_names.add(project_name)
            new_count += 1
        db.commit()
    finally:
        db.close()
    return {"new_projects": new_count, "region_updated": region_updated, "total_map": len(mapping)}
