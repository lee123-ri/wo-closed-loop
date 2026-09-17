"""alert 补派发 + 复用/合并 + 发生记录 回归。"""
from datetime import date, timedelta

from app.models import WorkOrder, WorkOrderMeasureLink, AnomalyOccurrence, DataPoolItem
from app.api.workorders import transition_work_order
from app.services.pool_service import generate_from_pool


def _make_host(db, code, phase="confirming", metric_type="power_gen", project_id=1):
    host = WorkOrder(
        code=code,
        title=f"测试异常{code}",
        reason="触发原因", action="行动要求",
        source_code="alert", status="judging", alert_phase=phase,
        priority="P1", region=None, created_date=date.today(),
        metric_type=metric_type, project_id=project_id,
        person_id=1, approver_id=11, type_id=1,
        planned_start_date=date.today(), deadline=date.today() + timedelta(days=3),
        backfill_reason="根因", backfill_action="措施",
        triggered_wo_tasks=[{"title": "措施1", "reason": "r", "action": "a"}],
    )
    db.add(host)
    db.flush()
    return host


def test_generate_records_occurrence(db):
    item = DataPoolItem(
        pool_type="anomaly", source_system="anomaly", source_ref="occ-1",
        title="测试", project_name=None, person_name="王小宁",
        description="d", status="pending", metric_type="power_gen",
        raw_data={"anomaly_type": "电量完成率偏低"},
    )
    db.add(item)
    db.flush()
    out = generate_from_pool(db, [item.id])
    wo = db.get(WorkOrder, out["work_order_ids"][0])
    occ = db.query(AnomalyOccurrence).filter_by(host_wo_id=wo.id).all()
    assert len(occ) == 1
    assert occ[0].metric_type == "power_gen"


def test_redispatch_back_to_tracking(client_auth, db):
    host = _make_host(db, "RW-HOST-RD", phase="reexamining")
    r = client_auth.post(f"/api/work-orders/{host.id}/redispatch", json={"measures": [{
        "title": "补派发措施",
        "person_name": "王小宁",
        "type_id": 1,
        "planned_start_date": date.today().isoformat(),
        "deadline": (date.today() + timedelta(days=2)).isoformat(),
        "reason": "复核未达标",
        "action": "继续整改",
    }]})
    assert r.status_code == 200, r.text
    assert r.json()["alert_phase"] == "tracking"
    links = db.query(WorkOrderMeasureLink).filter_by(host_wo_id=host.id).all()
    assert len(links) == 1
    m = db.get(WorkOrder, links[0].measure_wo_id)
    assert m.status == "dispatched"
    assert m.source_code == "measure"


def test_redispatch_wrong_phase_409(client_auth, db):
    host = _make_host(db, "RW-HOST-RD2", phase="tracking")
    r = client_auth.post(f"/api/work-orders/{host.id}/redispatch", json={"measures": [{"title": "x"}]})
    assert r.status_code == 409


def test_reuse_mounts_existing_measure(client_auth, db):
    a = _make_host(db, "RW-HOST-A", phase="confirming")
    transition_work_order(a.id, "confirm_analysis", db)
    measure_id = db.query(WorkOrderMeasureLink).filter_by(host_wo_id=a.id).all()[0].measure_wo_id

    b = _make_host(db, "RW-HOST-B", phase="confirming")
    r = client_auth.post(f"/api/work-orders/{b.id}/reuse", json={"measure_ids": [measure_id]})
    assert r.status_code == 200
    assert db.query(WorkOrderMeasureLink).filter_by(host_wo_id=b.id, measure_wo_id=measure_id, removed_at=None).first()


def test_merge_closes_source_and_moves_occurrence(client_auth, db):
    source = _make_host(db, "RW-HOST-SRC", phase="reexamining")
    target = _make_host(db, "RW-HOST-TGT", phase="tracking")
    db.add(AnomalyOccurrence(host_wo_id=source.id, occurred_at=date.today(), metric_type="power_gen", indicator_type="X", note="新建"))
    db.flush()

    r = client_auth.post(f"/api/work-orders/{source.id}/merge", json={"target_host_id": target.id})
    assert r.status_code == 200, r.text
    assert db.get(WorkOrder, source.id).status == "closed"
    assert db.get(WorkOrder, source.id).alert_phase == "recovered"
    occ = db.query(AnomalyOccurrence).filter_by(host_wo_id=target.id).all()
    # source 的 1 条发生记录迁入 + 1 条合并记录
    assert len(occ) == 2