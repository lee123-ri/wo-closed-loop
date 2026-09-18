"""清理「异常指标自动生成」的工单与数据池记录，重置回种子/手动/计划，配合 aitable.py 的 7 月过滤。

背景（2026-09-10）：异常指标表一次同步进了上万行（1月~7月+未标注），生成大量 monitor 工单。
用户拍板：只保留 7 月及以后；之前的 / 未标注的不进系统。

本脚本只删「异常自动生成」的数据，保留种子工单（RW-2026-00xx）、手动工单、年度计划(plan)工单及其数据池。

删除范围：
- 措施工单：source_code='measure'
- 自动生成的异常主单：source_code='alert' 且 parent_pool_id 非空（种子 alert 工单 parent_pool_id 为空，不受影响）
- 异常数据池：data_pool_items.pool_type='anomaly'

用法（在 backend 目录）：
  python ../scripts/cleanup_anomaly_20260910.py            # dry-run，只打印
  python ../scripts/cleanup_anomaly_20260910.py --apply    # 真删
"""
import sys

from sqlalchemy import text

sys.path.insert(0, ".")  # 让 `from app...` 可导入（从 backend 目录跑）

from app.core.database import engine  # noqa: E402

TARGET_IDS_SQL = """
SELECT id FROM work_orders
WHERE source_code = 'measure'
   OR (source_code = 'alert' AND parent_pool_id IS NOT NULL)
"""


def _ids() -> list[int]:
    with engine.connect() as c:
        return [r[0] for r in c.execute(text(TARGET_IDS_SQL))]


def _scalar(sql: str):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar()


def _exec(sql: str):
    with engine.begin() as c:
        c.execute(text(sql))


def main():
    apply_ = "--apply" in sys.argv
    tids = _ids()
    print("将删除的工单（自动生成异常相关）：", len(tids), "条")
    print("  其中 measure 措施工单：", _scalar("SELECT count(*) FROM work_orders WHERE source_code='measure'"))
    print("  其中 alert 异常主单：", _scalar("SELECT count(*) FROM work_orders WHERE source_code='alert' AND parent_pool_id IS NOT NULL"))
    print("将删除的异常数据池：", _scalar("SELECT count(*) FROM data_pool_items WHERE pool_type='anomaly'"), "条")
    print("保留的工单总数（含种子/手动/计划）：", _scalar("SELECT count(*) FROM work_orders WHERE NOT (source_code='measure' OR (source_code='alert' AND parent_pool_id IS NOT NULL))"))

    if not apply_:
        print("\n[dry-run] 加 --apply 才真正删除")
        return
    if not tids:
        print("\n无可删除的自动生成异常工单")
        return

    idstr = ",".join(map(str, tids))

    # 1) 断开子表引用（不依赖 FK cascade，最稳）
    for t in ("status_log", "attachments", "escalation_log", "notification_log"):
        _exec(f"DELETE FROM {t} WHERE work_order_id IN ({idstr})")
    _exec(f"DELETE FROM work_order_measure_links WHERE host_wo_id IN ({idstr}) OR measure_wo_id IN ({idstr})")
    _exec(f"DELETE FROM anomaly_occurrences WHERE host_wo_id IN ({idstr})")
    # 2) 断开指向这些工单的非级联引用
    _exec(f"UPDATE work_orders SET triggered_wo_id=NULL WHERE triggered_wo_id IN ({idstr})")
    _exec(f"UPDATE data_pool_items SET work_order_id=NULL WHERE work_order_id IN ({idstr})")
    # 3) 删工单 + 异常数据池
    _exec(f"DELETE FROM work_orders WHERE id IN ({idstr})")
    _exec("DELETE FROM data_pool_items WHERE pool_type='anomaly'")

    print("\n完成。剩余工单总数：", _scalar("SELECT count(*) FROM work_orders"),
          "；剩余异常数据池：", _scalar("SELECT count(*) FROM data_pool_items WHERE pool_type='anomaly'"))


if __name__ == "__main__":
    main()