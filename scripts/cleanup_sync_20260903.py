"""2026-09-03 一次性数据清理与同步脚本（李沛东派发重置 + 两路径同步 + 覆盖表）。

背景：上线前数据清理。
  1) 系统上派发给李沛东的工单全部重置回「待派发(pending)」，其他数据完全保留；
  2) 按 HS500 重点监控 8 项目（截图 2026-08-28），把两条路径已有的数据同步进来：
     路径A 年度运营计划非EAM（钉盘「工单版」xlsx → sync-drive）
     路径B aitable 异常数据（AI表格异常汇总表 → sync-aitable）
  3) 输出 8 项目 × 两来源 覆盖表，缺哪个来源由人工补齐。

用法（必须在 backend 目录下用 backend venv 运行，.env 按 cwd 加载）：
  cd backend
  .venv/bin/python ../scripts/cleanup_sync_20260903.py preview    # 只读：重置前分布 + 当前覆盖
  .venv/bin/python ../scripts/cleanup_sync_20260903.py reset     # 重置李沛东派发（先备份再跑！）
  .venv/bin/python ../scripts/cleanup_sync_20260903.py sync      # 两路径同步 + 8 项目生成工单
  .venv/bin/python ../scripts/cleanup_sync_20260903.py coverage  # 只读：覆盖表

重置语义与后端 transition reset 完全一致：
  来源状态 {approving,dispatched,executing,verifying,overdue,rejected} → pending，
  清空 oa_id/completed_date，overdue_days/escalation_level 归零，写 StatusLog。
  closed/pending/judging 等一律不动。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import or_, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models import DataPoolItem, Project, StatusLog, User, WorkOrder  # noqa: E402

PERSON = "李沛东"
RESETTABLE = ("approving", "dispatched", "executing", "verifying", "overdue", "rejected")
NOTE = "2026-09-03 数据清理·派发给李沛东的工单重置回待派发"
# 业务拍板（2026-09-03）：工单状态只保留三步，新工单初始落「待派发」
THREE_STEP = ("pending", "executing", "closed")

# 截图（2026-08-28 刘冰群消息）HS500 重点监控 8 项目 → 匹配关键词（系统项目名/来源项目名的子串）
PROJECTS = [
    ("协合盐源", ("盐源",)),
    ("中能建梭山", ("梭山",)),
    ("泰康师宗", ("师宗",)),
    ("青岛城投呼市", ("呼市", "呼和浩特")),
    ("青岛城投包头", ("包头",)),
    ("灵寿汇能", ("灵寿",)),
    ("邯郸张西堡", ("张西堡",)),
    ("景县煜特", ("煜特",)),
]


def _kw_filter(column, kws):
    return or_(*[column.ilike(f"%{k}%") for k in kws])


def _project_ids(db, kws) -> tuple[list[int], list[str]]:
    rows = db.execute(select(Project).where(_kw_filter(Project.name, kws))).scalars().all()
    return [p.id for p in rows], [p.name for p in rows]


def _print_coverage(db) -> None:
    print("\n═══ 8 项目 × 两来源 覆盖表 ═══")
    missing = []
    for label, kws in PROJECTS:
        pids, pnames = _project_ids(db, kws)
        # 路径A：年度运营计划非EAM（钉盘导入工单 source_code='plan'）
        plan_cnt = db.execute(
            select(WorkOrder.id).where(WorkOrder.source_code == "plan", WorkOrder.project_id.in_(pids or [-1]))
        ).all()
        # 路径B：aitable 异常数据（数据池 source_system='anomaly'）
        anom = db.execute(
            select(DataPoolItem).where(
                DataPoolItem.source_system == "anomaly",
                _kw_filter(DataPoolItem.project_name, kws) | _kw_filter(DataPoolItem.title, kws),
            )
        ).scalars().all()
        anom_gen = [a for a in anom if a.status == "generated"]
        # 附：aitable 非EAM（异常原因表 source_system='non_eam'）
        noneam_cnt = len(db.execute(
            select(DataPoolItem.id).where(
                DataPoolItem.source_system == "non_eam",
                _kw_filter(DataPoolItem.project_name, kws) | _kw_filter(DataPoolItem.title, kws),
            )
        ).all())

        a_ok, b_ok = len(plan_cnt) > 0, len(anom) > 0
        if not (a_ok and b_ok):
            miss = [n for n, ok in (("年度计划非EAM", a_ok), ("aitable异常", b_ok)) if not ok]
            missing.append((label, miss))
        print(
            f"{label:<10} | 项目表: {(','.join(pnames) or '未匹配!'):<18} "
            f"| 年度计划非EAM工单: {len(plan_cnt):>2} {'✓' if a_ok else '✗缺'} "
            f"| aitable异常: 池{len(anom)}/已生成{len(anom_gen)} {'✓' if b_ok else '✗缺'} "
            f"| (附)aitable非EAM: {noneam_cnt}"
        )
    print("─── 缺口汇总 ───")
    if missing:
        for label, miss in missing:
            print(f"{label}: 缺 {' + '.join(miss)}")
    else:
        print("无缺口：8 项目两来源齐全")
    print()


def cmd_preview(db) -> None:
    lp = db.execute(select(User).where(User.name == PERSON)).scalars().first()
    if not lp:
        print(f"[!] users 表无「{PERSON}」，无需重置")
    else:
        rows = db.execute(
            select(WorkOrder).where(WorkOrder.person_id == lp.id)
        ).scalars().all()
        by_status: dict[str, list[WorkOrder]] = {}
        for wo in rows:
            by_status.setdefault(wo.status, []).append(wo)
        print(f"═══ {PERSON} 名下工单 {len(rows)} 张，按状态分布 ═══")
        for st, wos in sorted(by_status.items()):
            tag = "← 将重置回 pending" if st in RESETTABLE else "（保留不动）"
            print(f"[{st}] {len(wos)} 张 {tag}")
            for wo in wos:
                print(f"    {wo.code} {wo.title[:40]}")
    _print_coverage(db)


def cmd_reset(db) -> None:
    lp = db.execute(select(User).where(User.name == PERSON)).scalars().first()
    if not lp:
        print(f"[!] users 表无「{PERSON}」，未做任何修改")
        return
    targets = db.execute(
        select(WorkOrder).where(WorkOrder.person_id == lp.id, WorkOrder.status.in_(RESETTABLE))
    ).scalars().all()
    if not targets:
        print(f"[=] {PERSON} 名下没有处于派发链状态的工单，无需重置")
        return
    for wo in targets:
        db.add(StatusLog(work_order_id=wo.id, from_status=wo.status, to_status="pending", note=NOTE))
        print(f"  重置 {wo.code} [{wo.status}→pending] {wo.title[:40]}")
        wo.status = "pending"
        wo.oa_id = None
        wo.completed_date = None
        wo.overdue_days = 0
        wo.escalation_level = 0
    db.commit()
    print(f"[ok] 共重置 {len(targets)} 张回 pending；其余工单（含 closed/pending）未改动")


def _to_initial(db, wo: WorkOrder, note: str, clear_person: bool) -> None:
    """把工单恢复回未派发初始态（三步状态规则的第一步 pending）。"""
    orig = wo.status
    db.add(StatusLog(work_order_id=wo.id, from_status=orig, to_status="pending", note=note))
    wo.status = "pending"
    wo.oa_id = None
    wo.completed_date = None
    wo.overdue_days = 0
    wo.escalation_level = 0
    wo.backfill_status = None
    wo.backfill_reason = None
    wo.backfill_action = None
    wo.backfilled_at = None
    wo.judgment_status = None
    wo.judgment_result = None
    wo.judgment_requested_at = None
    wo.judgment_completed_at = None
    if clear_person:
        wo.person_id = None
        wo.approver_id = None


def cmd_finalize(db) -> None:
    """终版清理（用户验收口径，2026-09-03 拍板）：
    1) 责任人=李沛东 的全部工单（含 closed/judging）→ 未派发初始态，清空责任人/审批人；
    2) 今天新导入/生成、且状态不在三步（pending/executing/closed）内的工单 → 回 pending
       （保留其责任人/审批人，只修状态与痕迹）。
    其余历史工单一律不动。
    """
    from datetime import date as _date
    n1 = n2 = 0
    lp = db.execute(select(User).where(User.name == PERSON)).scalars().first()
    if lp:
        for wo in db.execute(select(WorkOrder).where(WorkOrder.person_id == lp.id)).scalars().all():
            print(f"  [李] {wo.code} [{wo.status}→pending] 清责任人 {wo.title[:32]}")
            _to_initial(db, wo, f"{NOTE}(终版)", clear_person=True)
            n1 += 1
    today = _date.today()
    for wo in db.execute(
        select(WorkOrder).where(
            WorkOrder.created_date == today,
            WorkOrder.status.notin_(THREE_STEP),
        )
    ).scalars().all():
        print(f"  [新] {wo.code} [{wo.status}→pending] {wo.title[:32]}")
        _to_initial(db, wo, "2026-09-03 数据清理·新导入工单状态归初始(三步规则)", clear_person=False)
        n2 += 1
    db.commit()
    print(f"[ok] 终版清理：李沛东名下 {n1} 张全重置；今日新导入状态归零 {n2} 张；其余未动")


def cmd_sync(db) -> None:
    from app.services.dws_client import dws_status
    st = dws_status()
    print(f"[dws] {st}")
    if not st.get("authenticated"):
        print("[!] dws 未登录/凭证过期：先在本机恢复 dws 登录态（mac-bot-dws-restore），再重跑 sync")
        sys.exit(2)

    # 0. 项目映射入库（幂等），保证 drive 文件名匹配与区域PMO派发有项目表支撑
    from app.services.aitable import sync_anomaly_to_pool, sync_non_eam_to_pool, sync_project_map_to_db
    m = sync_project_map_to_db()
    print(f"[project-map] {m}")

    # 1. 路径A：钉盘年度运营计划 非EAM → 工单
    from app.services.drive_workorder_import import import_drive_workorder_versions
    d = import_drive_workorder_versions()
    print(f"[drive] imported={d['imported']} skipped_file={d['skipped_file']} files={d.get('files')}")
    for e in d.get("errors", [])[:10]:
        print(f"    drive错误: {e}")

    # 2. 路径B：aitable 异常 + 非EAM → 数据池（增量，按 recordId 去重不重复入池）
    a = sync_anomaly_to_pool(full=False)
    n = sync_non_eam_to_pool(full=False)
    print(f"[aitable] anomaly synced={a['synced']}/{a['total']} non_eam synced={n['synced']}/{n['total']}")
    for e in (a.get("errors", []) + n.get("errors", []))[:10]:
        print(f"    aitable错误: {e}")

    # 3. 8 项目的待生成池记录 → 工单（其余项目的池记录保留 pending，不批量生成）
    from app.services.pool_service import generate_from_pool
    ids: list[int] = []
    for _label, kws in PROJECTS:
        rows = db.execute(
            select(DataPoolItem.id).where(
                DataPoolItem.status == "pending",
                _kw_filter(DataPoolItem.project_name, kws) | _kw_filter(DataPoolItem.title, kws),
            )
        ).all()
        ids += [r[0] for r in rows]
    ids = sorted(set(ids))
    print(f"[generate] 8 项目待生成池记录 {len(ids)} 条")
    if ids:
        r = generate_from_pool(db, ids)
        print(f"[generate] generated={r['generated']} skipped={r['skipped']}")
        for e in r.get("errors", [])[:10]:
            print(f"    generate错误: {e}")
    db.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preview", "reset", "sync", "coverage", "finalize"])
    args = ap.parse_args()
    db = SessionLocal()
    try:
        if args.cmd == "preview":
            cmd_preview(db)
        elif args.cmd == "reset":
            cmd_reset(db)
        elif args.cmd == "sync":
            cmd_sync(db)
        elif args.cmd == "finalize":
            cmd_finalize(db)
        else:
            _print_coverage(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
