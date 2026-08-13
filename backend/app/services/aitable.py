"""钉钉 AI 表格同步服务 — 三表合一"""
import json
import subprocess
from datetime import date
from app.core.database import SessionLocal
from app.models import DataPoolItem, Project, User

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
        if proj:
            mapping[proj] = {"person": person, "eam": eam, "oms": oms, "pi": pi}
        if eam and eam not in mapping:
            mapping[eam] = {"person": person, "project": proj}
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
            db.add(DataPoolItem(
                pool_type="anomaly", source_system="anomaly", source_ref=rid,
                title=title, project_name=proj, person_name=person,
                description=f"异常月份: {month} | 区域: {region}",
                status="pending",
                raw_data={"anomaly_type": anomaly_type, "month": month, "region": region},
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
            db.add(DataPoolItem(
                pool_type="plan", source_system="non_eam", source_ref=rid,
                title=title, project_name=proj, person_name=person,
                description=f"{anomaly}: {reason}"[:1000],
                status="pending",
                raw_data={"anomaly": anomaly, "reason": reason, "region": region},
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