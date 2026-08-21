"""钉钉 AI 表格同步服务 — 三表合一"""
import json
import subprocess
from datetime import date
from app.core.database import SessionLocal
from app.models import DataPoolItem, Project, User
from app.services.region_map import normalize_region

# ── 三个数据源 ────────────────────────────────────────
ANOMALY_BASE = "OG9lyrgJPzMw9B5jSvpyvdQLWzN67Mw4"   # 数据池-异常指标
ANOMALY_TABLE = "j5hkt042bpz1m88o46iup"              # 汇总表

MAP_BASE = "1zknDm0WRaNwg5KkI0BwAMRy8BQEx5rG"       # 数据池-数仓
MAP_TABLE = "Dzp793M"                                 # 0映射表

PLAN_BASE = "bva6QBXJwanjQ4B6IMlleblnWn4qY5Pr"       # 数据池-计划
PLAN_TABLE = "bOywzmP"                                 # 异常原因表


def _dws(*args: str) -> dict:
    cmd = ["dws", *args, "--format", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    output = result.stdout.strip()
    if not output:
        raise RuntimeError(f"dws stdout empty, stderr: {result.stderr[:200]}")
    # 解析整个 JSON（可能跨多行）
    return json.loads(output)


def _get_records(base_id: str, table_id: str) -> list[dict]:
    data = _dws("aitable", "record", "query", "--base-id", base_id, "--table-id", table_id, "--all", "--page-limit", "0")
    result = data.get("data", data.get("result", data))
    return result.get("records", result.get("items", []))


def _cv(cells: dict, fid: str) -> str:
    """提取单元格值"""
    v = cells.get(fid)
    if v is None: return ""
    if isinstance(v, dict): return v.get("name", str(v))
    if isinstance(v, list) and v: return v[0].get("name", str(v[0])) if isinstance(v[0], dict) else str(v[0])
    return str(v)


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
            DataPoolItem.source_system == "anomaly", DataPoolItem.source_ref.isnot(None)
        ).all()
        existing_refs = {r[0] for r in existing}

    synced = 0; errors = []
    for r in records:
        rid = r.get("recordId", "")
        c = r.get("cells", {})
        if not full and rid in existing_refs: continue
        try:
            proj = _cv(c, "06h8ukzbt5k6lit2wupf2")     # OA项目名称
            person = _cv(c, "1kgnhr6fqota0ct19aqn6")     # 整改人
            anomaly_type = _cv(c, "dudwqcjgwobfozvuhgu7l") # 异常指标
            month = _cv(c, "6xwktuomtdhlqqd3iqh3q")       # 异常月份
            region = _cv(c, "rmnmea3m114npk2s537em")      # 区域
            title = f"{proj}-{anomaly_type}"[:512] if proj else anomaly_type[:512]
            # 全量存储原始 cell 数据，供后续提取计划开始时间等字段
            raw = {k: _cv(c, k) for k in c}
            raw.update({"anomaly_type": anomaly_type, "month": month, "region": region})
            db.add(DataPoolItem(
                pool_type="anomaly", source_system="anomaly", source_ref=rid,
                title=title, project_name=proj, person_name=person,
                description=f"异常月份: {month} | 区域: {region}",
                status="pending",
                raw_data=raw,
            ))
            synced += 1
        except Exception as e:
            errors.append(f"{rid}: {e}")
    db.commit(); db.close()
    return {"synced": synced, "errors": errors, "total": len(records)}


# ── 3. 异常原因 → 非EAM软工单 ──────────────────────────

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
        "aitable": {"anomaly_synced": a.get("synced", 0), "non_eam_synced": n.get("synced", 0)},
        "pool_generated": pool_generated,
        "drive_imported": drive.get("imported", 0),
        "drive_files": drive.get("files", 0),
        "errors": drive.get("errors", [])[:5],
    }


def sync_project_map_to_db() -> dict:
    """从数仓.0映射表同步项目到本地 projects 表（含区域=大区回填）"""
    mapping = sync_project_map()
    if not mapping:
        return {"new_projects": 0, "region_updated": 0, "message": "无数据"}
    db = SessionLocal()
    new_count = 0
    region_updated = 0
    try:
        seen = set()
        for proj_name, info in mapping.items():
            if not proj_name or len(proj_name) < 2 or proj_name in seen:
                continue
            seen.add(proj_name)
            project_name = info.get("project", proj_name)
            if not project_name or len(project_name) < 2:
                continue
            region = info.get("region", "")  # 大区
            existing = db.query(Project).filter(Project.name == project_name).first()
            if existing:
                # 已存在：回填/纠正区域为大区
                if region and existing.region != region:
                    existing.region = region
                    region_updated += 1
                continue
            code = project_name[:8]
            if db.query(Project).filter(Project.code == code).first():
                code = f"{project_name[:6]}{new_count}"
            db.add(Project(code=code, name=project_name, region=region))
            new_count += 1
        db.commit()
    finally:
        db.close()
    return {"new_projects": new_count, "region_updated": region_updated, "total_map": len(mapping)}