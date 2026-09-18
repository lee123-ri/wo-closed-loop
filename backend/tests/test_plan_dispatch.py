"""年度计划按月自动派发 + 计划类完整性门禁回归。"""
from datetime import date, datetime

from app.models import WorkOrder
from app.services.dingtalk import plan_completeness_missing
from app.services.plan_dispatch import _month_bounds, dispatch_monthly_plans


def _make_plan_wo(db, code, status="scheduled", planned=None, task_deliverable="调试日报"):
    wo = WorkOrder(
        code=code, title="计划措施", reason="根因", action="动作",
        task_deliverable=task_deliverable,
        source_code="plan", status=status, project_id=1,
        person_id=1, approver_id=11, type_id=1,
        created_date=date.today(),
        planned_start_date=planned or date.today(),
        deadline=date.today(),
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return wo


def test_month_bounds():
    first, nxt = _month_bounds(datetime(2026, 6, 15, 10, 0, 0))
    assert first == date(2026, 6, 1) and nxt == date(2026, 7, 1)
    first, nxt = _month_bounds(datetime(2026, 12, 1, 9, 0, 0))
    assert first == date(2026, 12, 1) and nxt == date(2027, 1, 1)


def test_plan_completeness_missing_deliverable(db):
    wo = _make_plan_wo(db, "RW-P-0001", task_deliverable=None)
    assert "任务目标交付物" in plan_completeness_missing(wo)
    wo.task_deliverable = "调试日报"
    db.commit()
    assert plan_completeness_missing(wo) == []


def test_dispatch_monthly_dispatches_complete_only(db, monkeypatch):
    """当月 + 完整 → 发起 OA 置 approving；缺交付物 → 跳过；非当月 → 不碰。"""
    import app.services.dingtalk as dt
    import app.services.plan_dispatch as pd

    # 复用当前测试会话（db 注入），避免函数自开会话看不到 fixture 未提交数据
    monkeypatch.setattr(dt, "create_oa_approval", lambda wo: "proc-1")

    this_month = date.today().replace(day=1)
    complete = _make_plan_wo(db, "RW-P-0010", planned=this_month)
    _make_plan_wo(db, "RW-P-0011", planned=this_month, task_deliverable=None)  # 缺交付物
    _make_plan_wo(db, "RW-P-0012", planned=date(2000, 1, 1))  # 非当月

    r = pd.dispatch_monthly_plans(db=db)
    assert r["dispatched"] == 1
    assert r["skipped_incomplete"] == 1
    db.refresh(complete)
    assert complete.status == "approving"
    assert complete.oa_id == "proc-1"


def test_dispatch_monthly_skips_existing_oa(db, monkeypatch):
    """已有真实 OA 实例（oa_id 非占位）的不重发——幂等。"""
    import app.services.dingtalk as dt
    import app.services.plan_dispatch as pd

    monkeypatch.setattr(dt, "create_oa_approval", lambda wo: "proc-2")

    this_month = date.today().replace(day=1)
    already = _make_plan_wo(db, "RW-P-0020", planned=this_month)
    already.oa_id = "real-oid-1"  # 已是真实 OA
    db.commit()

    r = pd.dispatch_monthly_plans(db=db)
    assert r["dispatched"] == 0
    db.refresh(already)
    assert already.status == "scheduled"  # 不推进
    assert already.oa_id == "real-oid-1"


def test_drive_import_dispatches_current_month_after_new_import(monkeypatch):
    """钉盘新导入当月计划后立即补派；空扫描不调用派发器。"""
    import app.services.drive_workorder_import as dwi
    import app.services.plan_dispatch as pd

    called = []
    expected = {"dispatched": 1, "skipped_incomplete": 0, "failed": 0}
    monkeypatch.setattr(pd, "dispatch_monthly_plans", lambda: called.append(True) or expected)

    assert dwi._dispatch_current_month_imports(1) == expected
    assert called == [True]
    assert dwi._dispatch_current_month_imports(0)["dispatched"] == 0
    assert called == [True]
