#!/usr/bin/env python3
"""回填项目/工单「区域」字段为大区（华北/东北/华东/华中/华南/西南/西北）。

数据修复：区域字段此前被写入了省份名（云南/河北 等），统一校正为大区。
大区由数仓「0映射表」的省份字段（v6ZTRXw）推导，只更新既有项目，不新建项目。

用法：
  cd backend && . .venv/bin/activate && python3 ../scripts/backfill_region.py

依赖 dws CLI（已认证），只读数仓 + 写本地库。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import text
from app.core.database import SessionLocal
from app.models import Project
from app.services.aitable import sync_project_map
from app.services.region_map import REGIONS, province_to_region


def main() -> None:
    # 1. 数仓映射（OA项目简称 → 大区），失败不阻断，走省份归一化兜底
    name2region: dict[str, str] = {}
    try:
        mapping = sync_project_map()
        for proj_name, info in mapping.items():
            region = info.get("region", "")
            if not region:
                continue
            # 主 key 是 OA项目简称；EAM 别名条目里的 project 也是简称
            name2region[proj_name] = region
            alias = info.get("project")
            if alias and alias != proj_name:
                name2region.setdefault(alias, region)
    except Exception as e:
        print(f"[warn] 数仓映射失败（继续用省份兜底）: {e}")

    db = SessionLocal()
    try:
        via_map = 0
        via_province = 0
        cleared = 0
        no_source = 0
        for p in db.query(Project).all():
            if p.region and p.region in REGIONS:
                continue  # 已是大区
            r = name2region.get(p.name, "")
            if r:
                p.region = r
                via_map += 1
            elif p.region:
                nr = province_to_region(p.region)
                if nr:
                    p.region = nr
                    via_province += 1
                else:
                    p.region = None  # 无法识别占位（如「测试区」）清空
                    cleared += 1
            else:
                no_source += 1  # 数仓无映射、原 region 也为空，保持空
        db.commit()
        print(f"[a] 数仓映射→大区: {via_map}")
        print(f"[b] 原省份名→大区: {via_province}")
        print(f"[c] 清空占位: {cleared}")
        print(f"[d] 无来源(保持空): {no_source}")

        # 2. 工单 region 跟随项目
        res = db.execute(text(
            """
            UPDATE work_orders w SET region = p.region
            FROM projects p
            WHERE w.project_id = p.id
              AND p.region IS NOT NULL
              AND (w.region IS NULL OR w.region <> p.region)
            """
        ))
        db.commit()
        print(f"[e] 工单 region 跟随项目: 更新 {res.rowcount} 行")
    finally:
        db.close()

    # 汇总
    db = SessionLocal()
    try:
        proj_rows = db.execute(text(
            "SELECT COALESCE(region,'<空>') r, COUNT(*) FROM projects GROUP BY 1 ORDER BY 2 DESC"
        )).fetchall()
        wo_rows = db.execute(text(
            "SELECT COALESCE(region,'<空>') r, COUNT(*) FROM work_orders GROUP BY 1 ORDER BY 2 DESC"
        )).fetchall()
    finally:
        db.close()

    print("\n== 项目区域分布 ==")
    for r_, n in proj_rows:
        print(f"  {r_}: {n}")
    print("== 工单区域分布 ==")
    for r_, n in wo_rows:
        print(f"  {r_}: {n}")


if __name__ == "__main__":
    main()