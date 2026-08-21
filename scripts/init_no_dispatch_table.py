#!/usr/bin/env python3
"""建「不发现场关闭台账」AITable 表（异常指标 Base 下），并把 tableId/字段映射写回本地库。

前置条件：
  - dws CLI 已认证，且当前账号对「数据池-异常指标」Base 有编辑权限（否则建表失败）
  - 已配置数据库连接（backend/.env）

用法：
  cd backend && . .venv/bin/activate && python3 ../scripts/init_no_dispatch_table.py

幂等：表已存在则按名解析复用；字段映射缺失则从 table get 兜底。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.aitable import (
    ANOMALY_BASE,
    NO_DISPATCH_TABLE_NAME,
    ensure_no_dispatch_table,
)


def main() -> None:
    print(f"Base    : {ANOMALY_BASE}")
    print(f"表名    : {NO_DISPATCH_TABLE_NAME}")
    cfg = ensure_no_dispatch_table()
    if not cfg:
        print("✗ 建表/解析失败（检查 dws 是否认证、账号是否有该 Base 编辑权限）")
        sys.exit(1)
    print("✓ 台账表就绪")
    print(f"  tableId : {cfg.get('table_id')}")
    print(f"  字段数  : {len(cfg.get('fields') or {})}")
    print("  字段映射:", cfg.get("fields"))
    print("后续「不发现场关闭」的工单会自动写入该台账；")
    print("若已有积压的 pending 记录，可由后台任务 sync_no_dispatch_records 补齐。")


if __name__ == "__main__":
    main()