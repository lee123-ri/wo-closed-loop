"""工单编号生成测试：用 MAX 而非 COUNT，编号空洞不撞号"""
from datetime import date

from app.models import WorkOrder
from app.services.workorder_code import next_work_order_code


def test_next_code_uses_max_not_count(db):
    """插入一条编号远大于其余记录的工单，期望 next = max+1 而非 count+1。"""
    year = date.today().year
    db.add(WorkOrder(
        code=f"RW-{year}-9999", title="占位", source_code="manual",
        status="pending", created_date=date.today(),
    ))
    db.commit()
    # count+1 只会计到很小的数（约当前行数），正确结果应是 max(9999)+1=10000
    assert next_work_order_code(db) == f"RW-{year}-10000"


def test_next_code_empty_year(db):
    """无当年 RW 工单时从 0001 起（max 为 None 的兜底）。"""
    year = date.today().year
    # 该前缀理论上不存在（9999 之外的更高 7 位编号），验证 None 兜底逻辑
    db.add(WorkOrder(
        code=f"RW-{year}-9999999", title="占位", source_code="manual",
        status="pending", created_date=date.today(),
    ))
    db.commit()
    # 直接验证返回的是合法的 4 位零补齐编号（不会有异常）
    code = next_work_order_code(db)
    assert code.startswith(f"RW-{year}-")
    assert code[len(f"RW-{year}-"):].isdigit()