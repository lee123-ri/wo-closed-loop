"""工单流转状态机测试"""
from datetime import date

from app.api.workorders import transition_work_order, create_work_order
from app.schemas.workorder import WorkOrderCreate
from app.models import WorkOrder


def test_full_transition_chain(db):
    """approving → dispatched → executing → verifying → closed（手动流转兜底）"""
    wo = create_work_order(WorkOrderCreate(
        title="测试工单", action="排查异响", source_code="manual",
        priority="P2", deadline=date.today(), project_id=1, person_id=1, approver_id=11,
    ), db)
    assert wo.status == "approving"

    # 派发
    wo = transition_work_order(wo.id, "dispatch", db)
    assert wo.status == "dispatched"
    assert wo.oa_id  # 应生成 OA 单号

    # 开始执行
    wo = transition_work_order(wo.id, "start_exec", db)
    assert wo.status == "executing"

    # 提交佐证
    wo = transition_work_order(wo.id, "submit_evidence", db)
    assert wo.status == "verifying"

    # 闭环
    wo = transition_work_order(wo.id, "close", db)
    assert wo.status == "closed"
    assert wo.completed_date is not None
    assert wo.conclusion  # 应有结论


def test_invalid_transition_blocked(db):
    """不可从 approving 直接开始执行（需先派发）"""
    wo = create_work_order(WorkOrderCreate(
        title="测试", action="做", source_code="manual", priority="P2",
        deadline=date.today(), project_id=1, person_id=1, approver_id=11,
    ), db)
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        transition_work_order(wo.id, "start_exec", db)
    assert exc.value.status_code == 409


def test_oa_generated_on_dispatch(db):
    """P1 建单即 approving，派发生成 OA"""
    wo = create_work_order(WorkOrderCreate(
        title="派发测试", action="做", source_code="alert", priority="P1",
        deadline=date.today(), project_id=1, person_id=1, approver_id=11,
    ), db)
    assert wo.status == "approving"
    wo2 = transition_work_order(wo.id, "dispatch", db)
    assert wo2.oa_id
