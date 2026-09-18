#!/usr/bin/env python3
"""上线前工单清场：只删除非闭环且没有真实钉钉 OA 实例的工单。

默认仅盘点；执行必须显式给出已完成且非空的 PostgreSQL 备份文件，并加 --apply。
保留的工单：已闭环，或关联真实 OA 实例且尚未终态。OA- 前缀为本地占位号，不算流程中。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import and_, func, or_, select, update

from app.core.database import SessionLocal
from app.models import DataPoolItem, WorkOrder


def retained_filter():
    """返回必须保留的谓词；与 OA 轮询对“真实实例”的判定一致。"""
    real_oa_in_progress = and_(
        WorkOrder.oa_id.isnot(None),
        ~WorkOrder.oa_id.like("OA-%"),
        ~WorkOrder.status.in_(("closed", "rejected")),
    )
    return or_(WorkOrder.status == "closed", real_oa_in_progress)


def preview(db) -> dict:
    rows = db.execute(
        select(WorkOrder.status, func.count()).group_by(WorkOrder.status).order_by(WorkOrder.status)
    ).all()
    total = db.scalar(select(func.count()).select_from(WorkOrder)) or 0
    keep = db.scalar(select(func.count()).select_from(WorkOrder).where(retained_filter())) or 0
    return {
        "total": total,
        "retain": keep,
        "delete": total - keep,
        "by_status": {status: count for status, count in rows},
        "rule": "保留 status=closed；或真实钉钉 OA 实例（oa_id 非空且不以 OA- 开头）且未终态。",
    }


def apply_cleanup(db) -> dict:
    target_ids = select(WorkOrder.id).where(~retained_filter())
    # 数据池记录不能留失效 FK；复位为待生成，以便上线后由管理员逐条勾选决定是否建单。
    pool_reset = db.execute(
        update(DataPoolItem)
        .where(DataPoolItem.work_order_id.in_(target_ids))
        .values(work_order_id=None, status="pending", skip_reason=None)
    ).rowcount
    # 触发工单的自关联无 ON DELETE，先解除指向待删除对象的引用。
    db.execute(update(WorkOrder).where(WorkOrder.triggered_wo_id.in_(target_ids)).values(triggered_wo_id=None))
    deleted = db.query(WorkOrder).filter(~retained_filter()).delete(synchronize_session=False)
    db.commit()
    return {"deleted_work_orders": deleted, "reset_pool_items": pool_reset}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行删除；默认只盘点")
    parser.add_argument("--backup-file", type=Path, help="已完成的 pg_dump 文件；执行删除时必填")
    args = parser.parse_args()
    if args.apply and (not args.backup_file or not args.backup_file.is_file() or args.backup_file.stat().st_size == 0):
        parser.error("--apply 需要一个已完成且非空的 --backup-file，拒绝在无回滚点时删除")

    db = SessionLocal()
    try:
        report = preview(db)
        if args.apply:
            report["applied"] = apply_cleanup(db)
        else:
            report["applied"] = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
