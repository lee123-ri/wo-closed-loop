"""工单流转状态机测试"""
from datetime import date

from app.api.workorders import transition_work_order, create_work_order
from app.schemas.workorder import WorkOrderCreate
from app.models import WorkOrder


def test_full_transition_chain(db):
    """approving → dispatched → executing → verifying → closed（手动流转兜底）"""
    wo = create_work_order(WorkOrderCreate(
        title="测试工单", action="排查异响", reason="异响应触发", source_code="manual",
        priority="P2", deadline=date.today(), project_id=1, person_id=1, approver_id=11,
        type_id=1, planned_start_date=date.today(),
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
        title="派发测试", action="做", reason="派发测试触发", source_code="meeting", priority="P1",
        deadline=date.today(), project_id=1, person_id=1, approver_id=11,
        type_id=1, planned_start_date=date.today(),
    ), db)
    assert wo.status == "approving"
    wo2 = transition_work_order(wo.id, "dispatch", db)
    assert wo2.oa_id


def test_live_oa_blocks_manual_transition(db):
    """已关联真实 OA 单据（非本地占位 OA- 前缀）时禁止平台手工流转；reset 保留兜底"""
    import pytest
    from fastapi import HTTPException

    wo = create_work_order(WorkOrderCreate(
        title="OA驱动测试", action="做", reason="人工流转应被拦截", source_code="meeting",
        priority="P2", deadline=date.today(), project_id=1, person_id=1, approver_id=11,
        type_id=1, planned_start_date=date.today(),
    ), db)

    # 模拟已发起真实钉钉审批：oa_id 为实例 ID（非 OA- 占位）
    entity = db.get(WorkOrder, wo.id)
    entity.oa_id = "real-oa-instance-001"
    db.commit()

    # approving + 真实 OA → 派发 / 驳回 均被拦截、且给出 OA 驱动提示
    for action in ("dispatch", "reject"):
        with pytest.raises(HTTPException) as exc:
            transition_work_order(wo.id, action, db)
        assert exc.value.status_code == 409
        assert "钉钉OA审批" in exc.value.detail

    # verifying + 真实 OA → 闭环（改成已闭环）同样被拦截
    entity.status = "verifying"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        transition_work_order(wo.id, "close", db)
    assert exc.value.status_code == 409
    assert "钉钉OA审批" in exc.value.detail

    # 重置兜底仍可走，并清空 OA 单号
    wo2 = transition_work_order(wo.id, "reset", db)
    assert wo2.status == "pending"
    assert wo2.oa_id is None
