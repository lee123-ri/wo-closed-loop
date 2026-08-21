"""工单编号生成：RW-YYYY-NNNN（4 位零补齐）。

统一用 MAX(code)+1 而非 COUNT+1：历史删除/回滚造成的编号空洞会让 count+1 生成
与已存在编号重复的值，触发 work_orders.code 唯一约束冲突（实测 dev 库曾出现）。
"""
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import WorkOrder


def next_work_order_code(db: Session) -> str:
    """返回下一个可用工单编号，如 RW-2026-0016。

    注意：仍非并发安全（多事务同时取号会撞唯一约束），与旧实现同级别的局限；
    对当前低并发建单场景足够。彻底解决需引入序列/重试，另行考虑。
    """
    year = date.today().year
    prefix = f"RW-{year}-"
    max_code = db.query(func.max(WorkOrder.code)).filter(
        WorkOrder.code.like(f"{prefix}%")
    ).scalar()
    nxt = 1
    if max_code and max_code.startswith(prefix):
        try:
            nxt = int(max_code[len(prefix):]) + 1
        except ValueError:
            pass
    return f"{prefix}{nxt:04d}"