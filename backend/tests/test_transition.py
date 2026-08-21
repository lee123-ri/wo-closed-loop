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


def test_resolve_oa_chain_shapes(db):
    """角色审批链解析：P1/P2/P3 形状 + 角色→人映射"""
    from app.services.roles import resolve_oa_chain, resolve_role_user_id

    def mk(priority):
        return create_work_order(WorkOrderCreate(
            title=f"链测试{priority}", action="做", source_code="manual",
            priority=priority, deadline=date.today(), project_id=1, person_id=1, approver_id=11,
        ), db)

    # P1：pmo + division_head + executor + approver
    chain_p1 = resolve_oa_chain(db, db.get(WorkOrder, mk("P1").id))
    assert [c["role"] for c in chain_p1] == ["pmo", "division_head", "executor", "approver"]
    assert [c["stage"] for c in chain_p1] == ["approve", "approve", "execute", "accept"]
    # 每个节点都解析到人（钉钉 userId 或姓名兜底，非空）
    assert all(c["dingtalk_id"] for c in chain_p1)
    # 角色节点 → 按 role_assignments 解析；执行/审批 → 按工单 person/approver
    assert chain_p1[0]["user_id"] == resolve_role_user_id(db, "pmo")
    assert chain_p1[1]["user_id"] == resolve_role_user_id(db, "division_head")
    assert chain_p1[2]["user_id"] == 1    # person_id=1
    assert chain_p1[3]["user_id"] == 11   # approver_id=11

    # P2：pmo + executor + approver
    chain_p2 = resolve_oa_chain(db, db.get(WorkOrder, mk("P2").id))
    assert [c["role"] for c in chain_p2] == ["pmo", "executor", "approver"]

    # P3：pmo + executor（无验收节点）
    chain_p3 = resolve_oa_chain(db, db.get(WorkOrder, mk("P3").id))
    assert [c["role"] for c in chain_p3] == ["pmo", "executor"]


def test_create_wo_persists_oa_progress(db):
    """建单应持久化 oa_progress（回调路由依赖）"""
    wo = create_work_order(WorkOrderCreate(
        title="进度持久化", action="做", source_code="manual", priority="P2",
        deadline=date.today(), project_id=1, person_id=1, approver_id=11,
    ), db)
    orm = db.get(WorkOrder, wo.id)
    assert orm.oa_progress
    assert [p["role"] for p in orm.oa_progress] == ["pmo", "executor", "approver"]
    assert all(p["approved"] is False for p in orm.oa_progress)
