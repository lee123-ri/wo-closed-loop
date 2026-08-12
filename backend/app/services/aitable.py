"""钉钉 AI 表格同步服务 — 只读拉取，不改 AI 表格"""
from datetime import date, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import DataPoolItem, Project, User

settings = get_settings()
_API = "https://api.dingtalk.com"

# ── 数据池-计划 · 表映射 ──────────────────────────────
PLAN_BASE_ID = "bva6QBXJwanjQ4B6IMlleblnWn4qY5Pr"
TABLE_EAM = "rEQsfQH"       # EAM工单
TABLE_MAP = "HohZcMa"       # 0映射表
TABLE_SUMMARY = "hERWDMS"   # 汇总表

# EAM工单 字段映射: fieldId → 含义
EAM_FIELDS = {
    "Q8hQIvs": "工单编号", "76m6r3i": "电场名称", "fWI4EpI": "资金计划编号",
    "m74CYR9": "三级科目", "xutBmyI": "预算月份", "M1dhKbL": "是否有计划",
    "ZZL3468": "区域", "E6jgOn7": "关闭时间", "quh9U6P": "实际完成时间",
    "aZBAtGh": "实际开始时间", "GOgskOl": "计划结束时间", "97Hj1c1": "计划开始时间",
    "MiFHZI2": "创建时间", "saQut80": "创建人", "RyeCQtw": "工作负责人",
    "PkwS8G3": "设备位置", "sqF84sv": "工单描述", "QRTLTzv": "记录编号",
    "SsIHmuU": "工单状态", "uFMIgBg": "工单类型", "87ME6mP": "场站性质",
}

# 0映射表 字段映射: fieldId → 含义
MAP_FIELDS = {
    "xOTtpZc": "项目简称", "3CiBorS": "项目状态", "lCTRByB": "交付单元",
    "2rzCUjb": "产品系列", "oEsnIdh": "装机容量", "4r51K73": "服务场景",
    "TMaSENb": "EAM名称", "GwRRDr1": "人力组织名称", "n9qGZOb": "预算归属部门",
    "3u99ofO": "数据填报系统", "hAy71oa": "集团独资名称", "i3okDTQ": "OMS名称",
    "4avsLpq": "PowerInsight名称", "IFHB40F": "场站第一负责人", "XkIJ9v5": "销售负责人",
    "v6ZTRXw": "省份", "f98Bp93": "市", "fsIwJeQ": "项目地址",
    "hIASavl": "业主简称", "pOc7MOD": "项目客户",
}


def _token() -> str | None:
    from app.services.dingtalk import get_access_token
    return get_access_token()


def _headers(token: str | None) -> dict:
    return {"x-acs-dingtalk-access-token": token or "", "Content-Type": "application/json"}


def _cell_val(cells: dict, field_id: str) -> str | None:
    """提取单元格值，处理 select/user 等复杂类型"""
    v = cells.get(field_id)
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("name", str(v))
    if isinstance(v, list):
        return v[0].get("name", str(v[0])) if v else None
    return str(v)


def _get_records(base_id: str, table_id: str, max_records: int = 2000) -> list[dict]:
    """只读拉取 AI 表格全部记录"""
    if not settings.dingtalk_app_key:
        print("[aitable] 未配置钉钉 app key，跳过")
        return []
    token = _token()
    if not token:
        print("[aitable] 无法获取 access token")
        return []
    records: list[dict] = []
    cursor = None
    while len(records) < max_records:
        params: dict[str, Any] = {"maxResults": 200}
        if cursor:
            params["nextToken"] = cursor
        try:
            resp = httpx.get(
                f"{_API}/v1.0/aitable/bases/{base_id}/tables/{table_id}/records",
                headers=_headers(token), params=params, timeout=30,
            )
            if resp.status_code != 200:
                print(f"[aitable] 读取失败: {resp.status_code} {resp.text[:200]}")
                break
            data = resp.json()
            batch = data.get("records", [])
            records.extend(batch)
            if not data.get("hasMore") or len(batch) == 0:
                break
            cursor = data.get("nextToken")
        except Exception as e:
            print(f"[aitable] 读取异常: {e}")
            break
    return records


# ── 项目/人员映射缓存 ──────────────────────────────────

def sync_project_map() -> dict:
    """从 0映射表 拉取项目→系统名称→负责人映射"""
    records = _get_records(PLAN_BASE_ID, TABLE_MAP)
    if not records:
        return {}
    mapping = {}
    for r in records:
        cells = r.get("cells", {})
        eam_name = _cell_val(cells, "TMaSENb") or ""
        oms_name = _cell_val(cells, "i3okDTQ") or ""
        pi_name = _cell_val(cells, "4avsLpq") or ""
        project_name = _cell_val(cells, "xOTtpZc") or ""
        person = _cell_val(cells, "IFHB40F") or ""
        province = _cell_val(cells, "v6ZTRXw") or ""
        owner = _cell_val(cells, "hIASavl") or ""
        product = _cell_val(cells, "2rzCUjb") or ""

        mapping[eam_name] = {
            "project_name": project_name,
            "oms_name": oms_name,
            "pi_name": pi_name,
            "person_name": person,
            "province": province,
            "owner": owner,
            "product": product,
        }
        if oms_name:
            mapping[oms_name] = mapping[eam_name]
        if project_name:
            mapping[project_name] = mapping[eam_name]
    return mapping


# ── 主同步逻辑 ─────────────────────────────────────────

def sync_eam_to_pool(full: bool = False) -> dict:
    """从 EAM工单表 同步到 data_pool_items

    只读操作，不修改 AI 表格任何内容。
    full=True: 全量同步，否则只同步新记录。
    """
    db = SessionLocal()
    records = _get_records(PLAN_BASE_ID, TABLE_EAM)
    if not records:
        db.close()
        return {"synced": 0, "skipped": 0, "errors": ["无数据或 API 不可用"]}

    # 拉取项目映射
    project_map = sync_project_map()

    # 已有记录去重
    existing_refs = set()
    if not full:
        existing = db.query(DataPoolItem.source_ref).filter(
            DataPoolItem.source_system == "aitable",
            DataPoolItem.source_ref.isnot(None),
        ).all()
        existing_refs = {r[0] for r in existing}

    synced = 0
    skipped = 0
    errors: list[str] = []

    for r in records:
        record_id = r.get("recordId", "")
        cells = r.get("cells", {})

        if not full and record_id in existing_refs:
            skipped += 1
            continue

        try:
            station_name = _cell_val(cells, "76m6r3i") or ""
            person_name = _cell_val(cells, "RyeCQtw") or ""
            status_raw = _cell_val(cells, "SsIHmuU") or ""
            desc = _cell_val(cells, "sqF84sv") or ""
            wo_type = _cell_val(cells, "uFMIgBg") or ""

            # 从映射表匹配项目
            proj_info = project_map.get(station_name, {})
            matched_project = proj_info.get("project_name", station_name)
            mapped_person = proj_info.get("person_name", person_name)

            # 解析日期
            dl_str = _cell_val(cells, "GOgskOl") or _cell_val(cells, "97Hj1c1")
            deadline = None
            if dl_str:
                try:
                    deadline = date.fromisoformat(dl_str[:10])
                except (ValueError, TypeError):
                    pass

            # 判断是否生成了工单
            pool_status = "pending"
            if status_raw in ("关闭",):
                pool_status = "skipped"
                skipped += 1

            item = DataPoolItem(
                pool_type="plan",
                source_system="aitable",
                source_ref=record_id,
                title=f"{station_name}-{desc}"[:512] if station_name else desc[:512],
                project_name=matched_project,
                person_name=mapped_person,
                deadline=deadline,
                description=desc,
                status=pool_status,
                raw_data={
                    "station": station_name,
                    "person": person_name,
                    "status": status_raw,
                    "type": wo_type,
                    "record_id": record_id,
                    **{EAM_FIELDS.get(k, k): _cell_val(cells, k) for k in list(cells.keys())[:15]},
                },
            )
            db.add(item)
            synced += 1
        except Exception as e:
            errors.append(f"记录 {record_id}: {e}")

    db.commit()
    db.close()
    return {"synced": synced, "skipped": skipped, "errors": errors, "total_aitable": len(records)}


def sync_project_map_to_db() -> dict:
    """从 0映射表 同步项目信息到本地 projects 表"""
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
            db.add(Project(
                code=code,
                name=proj_name,
                type="wind" if "风电" in proj_name else "pv" if "光伏" in proj_name else None,
                region=info.get("province"),
            ))
            updated += 1
        db.commit()
    finally:
        db.close()
    return {"updated": updated, "total_map": len(mapping)}