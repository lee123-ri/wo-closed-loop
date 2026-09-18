"""历史监视告警(alert)主单的 alert_phase 回填：把 09-10 之前的 alert 主单从「三步」归位到五阶段。

背景（2026-09-11）：五阶段闭环上线后，历史 alert 主单因 alert_phase 为空（h002 迁移只加列未回填），
在前端仍按三步（待派发→执行中→已闭环）展示、且不出现「措施草稿」表单，导致无法手写措施工单。

本条只回填真正的主单，规则如下 ——

范围（source_code='alert' 且 alert_phase IS NULL），并排除旧流程里被误标成 alert 的「措施单B」：
  NOT id IN (SELECT triggered_wo_id FROM work_orders WHERE triggered_wo_id IS NOT NULL)

按 status 归位（不触碰 status，只补 alert_phase）：
  status = 'judging'  → alert_phase = 'confirming'   # 已回填、卡在「分析确认」，回填后即可手写措施草稿
  status = 'closed'   → alert_phase = 'recovered'    # 历史已闭环 → 五阶段终态「已恢复」
  status = 'pending'  → 不动                          # 待回填，五阶段从回填后才开始
  其它 status          → 不动                          # 单发动过 OA 的遗留 alert / 手动建，不强行套五阶段

每条被回填的单写一条 StatusLog，note 前缀「历史回填·阶段归位」，便于时间线与复盘。

用法（在 backend 目录，需 .venv 激活后与本地 PG 连通）：
  python ../scripts/backfill_alert_phase_20260911.py            # dry-run，只打印分组计数与样例编号
  python ../scripts/backfill_alert_phase_20260911.py --apply    # 真写
"""
import sys

from sqlalchemy import text

sys.path.insert(0, ".")  # 让 `from app...` 可导入（从 backend 目录跑）

from app.core.database import engine  # noqa: E402

# 主单 = alert 且 alert_phase 为空，且不是「旧流程措施单B」（被某主单 triggered_wo_id 引用的 alert 单）
SCOPE_SQL = """
SELECT id, code, status, metric_type
FROM work_orders
WHERE source_code = 'alert'
  AND alert_phase IS NULL
  AND id NOT IN (
      SELECT triggered_wo_id FROM work_orders WHERE triggered_wo_id IS NOT NULL
  )
ORDER BY status, id
"""

PHASE_MAP = {
    "judging": "confirming",
    "closed": "recovered",
}


def _rows() -> list[tuple]:
    with engine.connect() as c:
        return [tuple(r) for r in c.execute(text(SCOPE_SQL))]


def main():
    apply_ = "--apply" in sys.argv
    rows = _rows()

    # 分组统计，供人工核对
    by_status: dict[str, int] = {}
    to_backfill = []
    for wid, code, status, metric in rows:
        by_status[status] = by_status.get(status, 0) + 1
        if status in PHASE_MAP:
            to_backfill.append((wid, code, status, metric))

    print("=== 历史 alert 主单（alert_phase 为空）分布 ===")
    if not by_status:
        print("  （无 —— 没有需要回填的 alert 主单，退出）")
        return
    for s, n in sorted(by_status.items()):
        mark = "→ " + PHASE_MAP[s] if s in PHASE_MAP else "· 不动"
        print(f"  status={s:12s}  {n:4d} 条  {mark}")

    print()
    print(f"将回填：{len(to_backfill)} 条")
    for wid, code, status, metric in to_backfill:
        print(f"  {code}  {status} → {PHASE_MAP[status]}  (metric_type={metric or '—'})")

    if not apply_:
        print("\n[dry-run] 加 --apply 才真正写入（幂等：回填后重新跑不会再命中）")
        return

    if not to_backfill:
        print("\n无可回填的 alert 主单")
        return

    with engine.begin() as c:
        for wid, code, status, metric in to_backfill:
            new_phase = PHASE_MAP[status]
            c.execute(
                text("UPDATE work_orders SET alert_phase = :p WHERE id = :id"),
                {"p": new_phase, "id": wid},
            )
            c.execute(
                text(
                    "INSERT INTO status_log (work_order_id, from_status, to_status, operator_id, note, created_at, updated_at) "
                    "VALUES (:wid, :fs, :ts, NULL, :note, now(), now())"
                ),
                {
                    "wid": wid,
                    "fs": status,
                    "ts": status,
                    "note": f"历史回填·阶段归位 → {new_phase}",
                },
            )
    print(f"\n已回填 {len(to_backfill)} 条 alert 主单的 alert_phase，并写入对应 StatusLog。")


if __name__ == "__main__":
    main()