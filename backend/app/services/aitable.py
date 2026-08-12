"""钉钉 AI 表格同步服务 — 通过 dws CLI 只读拉取"""
import json
import subprocess
from datetime import date, datetime
from typing import Any

from app.core.database import SessionLocal
from app.models import DataPoolItem, Project, User

# ── 数据池-计划 · 表映射 ──────────────────────────────
PLAN_BASE_ID = "bva6QBXJwanjQ4B6IMlleblnWn4qY5Pr"
TABLE_ANOMALY = "bOywzmP"   # 异常原因表 — 非EAM软工单主数据源
TABLE_SUMMARY = "hERWDMS"   # 汇总表 — 异常标记辅助

# EAM工单 字段映射: fieldId → 含义
EAM_FIELDS = {
    "Q8hQIvs": "工单编号", "76m6r3i": "电场名称", "fWI4EpI": "资金计划编号",
    "m74CYR9": "三级科目", "xutBmyI": "预算月份", "M1dhKbL": "是否有计划",
    "ZZL3468": "区域", "quh9U6P": "实际完成时间", "aZBAtGh": "实际开始时间",
    "GOgskOl": "计划结束时间", "97Hj1c1": "计划开始时间", "MiFHZI2": "创建时间",
    "saQut80": "创建人", "RyeCQtw": "工作负责人", "PkwS8G3": "设备位置",
    "sqF84sv": "工单描述", "QRTLTzv": "记录编号", "SsIHmuU": "工单状态",
    "uFMIgBg": "工单类型", "87ME6mP": "场站性质",
}

MAP_FIELDS = {
    "xOTtpZc": "项目简称", "3CiBorS": "项目状态", "2rzCUjb": "产品系列",
    "TMaSENb": "EAM名称", "i3okDTQ": "OMS名称", "4avsLpq": "PowerInsight名称",
    "IFHB40F": "场站第一负责人", "v6ZTRXw": "省份", "hIASavl": "业主简称",
}


def _dws(*args: str) -> dict:
    """调用 dws CLI 并返回 JSON"""
    cmd = ["dws", *args, "--format", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"dws failed: {result.stderr[:200]}")
    return json.loads(result.stdout)


def _get_records(base_id: str, table_id: str) -> list[dict]:
    """通过 dws CLI 只读拉取 AI 表格全部记录"""
    data = _dws("aitable", "record", "query", "--base-id", base_id, "--table-id", table_id, "--all", "--page-limit", "0")
    result = data.get("data", data.get("result", data))
    return result.get("records", result.get("items", []))


def _cell_val(cells: dict, field_id: str) -> str | None:
    v = cells.get(field_id)
    if v is None: return None
    if isinstance(v, dict): return v.get("name", str(v))
    if isinstance(v, list) and v: return v[0].get("name", str(v[0])) if isinstance(v[0], dict) else str(v[0])
    return str(v)


def sync_project_map() -> dict:
    """从 0映射表 拉取项目映射"""
    try:
        records = _get_records(PLAN_BASE_ID, TABLE_MAP)
    except Exception as e:
        print(f"[aitable] 映射表读取失败: {e}")
        return {}
    mapping = {}
    for r in records:
        cells = r.get("cells", {})
        eam = _cell_val(cells, "TMaSENb") or ""
        oms = _cell_val(cells, "i3okDTQ") or ""
        proj = _cell_val(cells, "xOTtpZc") or ""
        person = _cell_val(cells, "IFHB40F") or ""
        mapping[eam] = {"project_name": proj, "oms_name": oms, "person_name": person}
        if oms: mapping[oms] = mapping[eam]
        if proj: mapping[proj] = mapping[eam]
    return mapping


def sync_anomaly_to_pool(full: bool = False) -> dict:
    """从异常原因表同步非EAM软工单到 data_pool_items

    异常原因表 (bOywzmP) 字段映射:
      ivATb5i → 待异常原因反馈 (描述)
      UjHVcMP → 异常原因 (异常甄别类型)
      iR5P7hE → 区域
      mAFIHjj → OA项目
      Mp4xZHB → 项目第一负责人
      RMi2RbF → 预算下发月份
    """
    try:
        records = _get_records(PLAN_BASE_ID, TABLE_ANOMALY)
    except Exception as e:
        return {"synced": 0, "skipped": 0, "errors": [f"dws CLI 调用失败: {e}"]}

    if not records:
        return {"synced": 0, "skipped": 0, "errors": ["异常原因表返回空数据"]}

    db = SessionLocal()

    existing_refs = set()
    if not full:
        existing = db.query(DataPoolItem.source_ref).filter(
            DataPoolItem.source_system == "aitable_anomaly", DataPoolItem.source_ref.isnot(None)
        ).all()
        existing_refs = {r[0] for r in existing}

    synced = 0; skipped = 0; errors: list[str] = []

    for r in records:
        record_id = r.get("recordId", "")
        cells = r.get("cells", {})

        if not full and record_id in existing_refs:
            skipped += 1; continue

        try:
            anomaly_type = _cell_val(cells, "UjHVcMP") or ""
            reason_text = _cell_val(cells, "ivATb5i") or ""
            region = _cell_val(cells, "iR5P7hE") or ""
            project = _cell_val(cells, "mAFIHjj") or ""
            person = _cell_val(cells, "Mp4xZHB") or ""
            month = _cell_val(cells, "RMi2RbF") or ""

            desc = f"{anomaly_type}: {reason_text}"[:1000]
            title = f"{project}-{anomaly_type}"[:512] if project else anomaly_type[:512]

            pool_status = "pending"

            item = DataPoolItem(
                pool_type="anomaly", source_system="aitable_anomaly", source_ref=record_id,
                title=title, project_name=project, person_name=person,
                description=desc, status=pool_status,
                raw_data={
                    "anomaly_type": anomaly_type, "reason": reason_text,
                    "region": region, "project": project, "person": person, "month": month,
                },
            )
            db.add(item); synced += 1
        except Exception as e:
            errors.append(f"记录 {record_id}: {e}")

    db.commit(); db.close()
    return {"synced": synced, "skipped": skipped, "errors": errors, "total_aitable": len(records)}


def sync_project_map_to_db() -> dict:
    """从 0映射表 同步项目信息"""
    mapping = sync_project_map()
    if not mapping:
        return {"updated": 0, "message": "无数据"}
    db = SessionLocal()
    updated = 0
    try:
        existing = {p.code: p for p in db.query(Project).all()}
        for eam_name, info in mapping.items():
            proj_name = info["project_name"]
            if not proj_name or len(proj_name) < 2:
                continue
            code = proj_name[:8]
            if code in existing:
                continue
            db.add(Project(code=code, name=proj_name, type=None, region=None))
            updated += 1
        db.commit()
    finally:
        db.close()
    return {"updated": updated, "total_map": len(mapping)}