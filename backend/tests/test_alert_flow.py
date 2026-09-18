"""alert 五阶段流转回归：确认分析→派发→跟踪→闭环回写 2/11→复核→闭环。

直接调 transition_work_order（复用 test_transition 的方式），不依赖钉钉真实接口（conftest 的
_mock_oa_in_tests 已把 oa_configured→False / create_oa_approval→None）。
"""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.api.workorders import transition_work_order
from app.models import WorkOrder, WorkOrderMeasureLink
from app.services.pool_service import measure_progress, _notify_measure_closed


def _make_host(db, phase="confirming"):
    host = WorkOrder(
        code="RW-HOST-1",
        title="测试异常指标工单",
        reason="触发原因", action="行动要求",
        source_code="reliability", metric_type="reliability", status="judging", alert_phase=phase,
        priority="P1", region=None, created_date=date.today(),
        project_id=1, person_id=1, approver_id=11, type_id=1,
        planned_start_date=date.today(), deadline=date.today() + timedelta(days=3),
        backfill_reason="根因", backfill_action="措施",
        triggered_wo_tasks=[{"title": f"措施{i}", "reason": "r", "action": "a"} for i in range(2)],
    )
    db.add(host)
    db.flush()
    return host


def _links(db, host_id):
    return db.query(WorkOrderMeasureLink).filter_by(host_wo_id=host_id).all()


def test_confirm_analysis_creates_pending_measures_and_links(db):
    host = _make_host(db)
    out = transition_work_order(host.id, "confirm_analysis", db)
    assert out.alert_phase == "dispatching"

    links = _links(db, host.id)
    assert len(links) == 2
    for l in links:
        m = db.get(WorkOrder, l.measure_wo_id)
        assert m.status == "pending"
        assert m.source_code == "reliability"
    p = measure_progress(db, host.id)
    assert p["closed"] == 0 and p["total"] == 2


def test_dispatch_measures_then_tracking(db):
    host = _make_host(db)
    transition_work_order(host.id, "confirm_analysis", db)
    out = transition_work_order(host.id, "dispatch_measures", db)
    assert out.alert_phase == "tracking"
    for l in _links(db, host.id):
        assert db.get(WorkOrder, l.measure_wo_id).status == "dispatched"


def test_measure_close_updates_progress_then_reexamining(db):
    host = _make_host(db)
    transition_work_order(host.id, "confirm_analysis", db)
    transition_work_order(host.id, "dispatch_measures", db)

    links = _links(db, host.id)
    # 关第 1 条措施 → 1/2，仍 tracking
    m1 = db.get(WorkOrder, links[0].measure_wo_id)
    m1.status = "closed"
    db.flush()
    _notify_measure_closed(db, m1)
    db.flush()
    host = db.get(WorkOrder, host.id)
    assert host.alert_phase == "tracking"
    p = measure_progress(db, host.id)
    assert p["closed"] == 1 and p["total"] == 2

    # 关第 2 条 → 2/2，自动置 reexamining
    m2 = db.get(WorkOrder, links[1].measure_wo_id)
    m2.status = "closed"
    db.flush()
    _notify_measure_closed(db, m2)
    db.flush()
    host = db.get(WorkOrder, host.id)
    assert host.alert_phase == "reexamining"
    p = measure_progress(db, host.id)
    assert p["closed"] == 2 and p["total"] == 2


def test_confirm_recovered_closes_with_recovered(db):
    host = _make_host(db, phase="reexamining")
    out = transition_work_order(host.id, "confirm_recovered", db)
    assert out.status == "closed"
    assert out.alert_phase == "recovered"
    assert out.completed_date is not None


def test_phase_guard_blocks_wrong_order(db):
    host = _make_host(db)  # confirming
    with pytest.raises(HTTPException) as e:
        transition_work_order(host.id, "dispatch_measures", db)  # 需 dispatching
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        transition_work_order(host.id, "confirm_recovered", db)  # 需 reexamining
    assert e.value.status_code == 409


def test_close_without_measure_on_host_recovers(db):
    """confirming 阶段「无需措施直接闭环」→ closed + recovered。"""
    host = _make_host(db)
    out = transition_work_order(host.id, "close", db)
    assert out.status == "closed"
    assert out.alert_phase == "recovered"