import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models import DataPoolItem, WorkOrder
from scripts.prelaunch_workorder_cleanup import apply_cleanup, preview


def _wo(code, status, oa_id=None):
    return WorkOrder(code=code, title=code, source_code="manual", status=status, oa_id=oa_id, created_date=date.today())


def test_prelaunch_cleanup_keeps_closed_and_real_oa_only(db):
    closed = _wo("RW-clean-closed", "closed")
    active_oa = _wo("RW-clean-oa", "approving", "proc-real-1")
    draft = _wo("RW-clean-draft", "pending")
    fake_oa = _wo("RW-clean-fake", "approving", "OA-20260918-001")
    db.add_all([closed, active_oa, draft, fake_oa])
    db.flush()
    closed_id, active_oa_id, draft_id = closed.id, active_oa.id, draft.id
    pool = DataPoolItem(pool_type="anomaly", source_system="test", title="待复位", status="generated", work_order_id=draft.id)
    db.add(pool)
    db.commit()

    report = preview(db)
    assert report["retain"] >= 2
    result = apply_cleanup(db)
    assert result["deleted_work_orders"] == report["delete"]
    assert db.get(WorkOrder, closed_id) is not None
    assert db.get(WorkOrder, active_oa_id) is not None
    assert db.get(WorkOrder, draft_id) is None
    db.refresh(pool)
    assert pool.status == "pending" and pool.work_order_id is None
