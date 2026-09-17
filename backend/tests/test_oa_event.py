"""OA 审批事件 → 平台状态同步测试（apply_oa_event）。

锁定真实模板的 2 节点审批流映射：责任人(执行/提交佐证) → 审批人(确认闭环)。
  责任人节点通过（提交佐证）→ verifying（待验收）
  审批人节点通过 → 实例 COMPLETED → closed
  任意节点拒绝     → rejected
推进只依赖钉钉实例现状（已通过节点数），天然幂等。
真实 API 的 tasks[].task_result 是大写 "AGREE"/"REFUSE"/"NONE"，测试 mock 对齐。
"""
from datetime import date

from app.models import WorkOrder
from app.services.oa_event import apply_oa_event


def _make_wo(db, code="RW-OAT-0001", status="approving", oa_id="proc-1"):
    wo = WorkOrder(
        code=code, title="测试", reason="触发", action="做",
        source_code="manual", status=status, oa_id=oa_id,
        project_id=1, person_id=1, approver_id=11,
        created_date=date.today(), deadline=date.today(),
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return wo


def _info(status="RUNNING", result="", approved=0, with_tasks=True):
    """构造 query_oa_approval 返回（规范化的 process_instance 字典）。

    tasks 按真实模板造 2 个审批节点：已通过的任务 task_result="AGREE"、task_status="COMPLETED"，
    未到的任务 task_result="NONE"、task_status="RUNNING"。
    """
    tasks = None
    if with_tasks:
        tasks = []
        for i in range(2):
            if i < approved:
                tasks.append({"userid": f"u{i}", "task_status": "COMPLETED", "task_result": "AGREE"})
            else:
                tasks.append({"userid": f"u{i}", "task_status": "RUNNING", "task_result": "NONE"})
    return {
        "process_instance_id": "proc-1",
        "status": status,
        "result": result,
        "form_component_values": [],
        "tasks": tasks,
    }


def test_advance_by_node_count(db, monkeypatch):
    """按已通过节点数推进：1→verifying，COMPLETED→closed"""
    import app.services.dingtalk as dt

    wo = _make_wo(db)
    assert wo.status == "approving"

    monkeypatch.setattr(dt, "query_oa_approval", lambda pid: _info(approved=1))
    r = apply_oa_event({"processInstanceId": "proc-1"}, db)
    assert r["status"] == "verifying"
    db.refresh(wo)
    assert wo.status == "verifying"

    monkeypatch.setattr(dt, "query_oa_approval",
                        lambda pid: _info(status="COMPLETED", result="agree", approved=2))
    r = apply_oa_event({"processInstanceId": "proc-1"}, db)
    assert r["status"] == "closed"
    db.refresh(wo)
    assert wo.status == "closed"
    assert wo.completed_date is not None
    assert wo.conclusion


def test_refuse_rejects(db, monkeypatch):
    """任意节点拒绝 → rejected"""
    import app.services.dingtalk as dt

    wo = _make_wo(db, code="RW-OAT-0002")
    monkeypatch.setattr(dt, "query_oa_approval",
                        lambda pid: _info(status="TERMINATED", result="refuse"))
    r = apply_oa_event({"processInstanceId": "proc-1"}, db)
    assert r["status"] == "rejected"
    db.refresh(wo)
    assert wo.status == "rejected"


def test_idempotent_on_redelivery(db, monkeypatch):
    """同一节点状态重复推送/轮询，不应重复推进（幂等）"""
    import app.services.dingtalk as dt

    wo = _make_wo(db, code="RW-OAT-0003")
    monkeypatch.setattr(dt, "query_oa_approval", lambda pid: _info(approved=1))
    apply_oa_event({"processInstanceId": "proc-1", "result": "agree",
                    "activityName": "责任节点"}, db)
    db.refresh(wo)
    assert wo.status == "verifying"

    # 重推：仍是 1 个通过节点，不应再变化（更不能提前闭环）
    apply_oa_event({"processInstanceId": "proc-1", "result": "agree",
                    "activityName": "责任节点"}, db)
    db.refresh(wo)
    assert wo.status == "verifying"


def test_fallback_when_no_tasks(db, monkeypatch):
    """查询结果缺 tasks 时，走兜底：责任人提交佐证 → verifying（而非 dispatched/executing）"""
    import app.services.dingtalk as dt

    wo = _make_wo(db, code="RW-OAT-0004")
    monkeypatch.setattr(dt, "query_oa_approval", lambda pid: _info(with_tasks=False))
    r = apply_oa_event({"processInstanceId": "proc-1", "result": "agree",
                        "activityName": "责任节点"}, db)
    assert r["status"] == "verifying"