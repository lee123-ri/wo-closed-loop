"""管理员工单操作回归：详情页编辑基本信息 + 删除「起不了状态」的废单。

背景（2026-09-14）：管理员需要在详情页可直接改工单基本信息（标题/原因/行动/结论/
项目/类型/责任人/审批人/优先级/区域/三个日期），并能删除卡死的废单；
两个入口都仅管理员可用（require_admin），删废单需清理子记录并解除非级联外键引用。
"""
from datetime import date

from app.api.workorders import create_work_order
from app.models import DataPoolItem, WorkOrder
from app.schemas.workorder import WorkOrderCreate


def _mk_wo(db):
    """建一条 manual 工单（走 create_work_order，状态落到 approving）。"""
    return create_work_order(WorkOrderCreate(
        title="管理端编辑删除测试", action="做", reason="测", source_code="manual",
        priority="P2", deadline=date.today(), project_id=1, person_id=1, approver_id=11,
        type_id=1, planned_start_date=date.today(),
    ), db)


def _executor_headers(db):
    from app.core.security import create_access_token
    from app.models import User
    u = db.query(User).filter(User.role == "executor").first()
    token = create_access_token(str(u.id), extra={"name": u.name, "role": u.role})
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_edit_basic_info(client_auth, db):
    wo = _mk_wo(db)
    r = client_auth.patch(f"/api/work-orders/{wo.id}/basic", json={
        "title": "改过的标题", "priority": "P1", "region": "华北",
        "conclusion": "待验收结论", "deadline": "2026-09-30",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "改过的标题"
    assert body["priority"] == "P1"
    assert body["region"] == "华北"
    assert body["conclusion"] == "待验收结论"
    assert body["deadline"] == "2026-09-30"


def test_basic_edit_requires_admin(client, db):
    wo = _mk_wo(db)
    r = client.patch(f"/api/work-orders/{wo.id}/basic", json={"title": "越权改"},
                     headers=_executor_headers(db))
    assert r.status_code == 403


def test_basic_edit_rejects_empty_title(client_auth, db):
    wo = _mk_wo(db)
    r = client_auth.patch(f"/api/work-orders/{wo.id}/basic", json={"title": "   "})
    assert r.status_code == 400


def test_admin_can_delete_work_order(client_auth, db):
    wo = _mk_wo(db)
    wid = wo.id
    r = client_auth.delete(f"/api/work-orders/{wid}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    # 再取应 404
    assert client_auth.get(f"/api/work-orders/{wid}").status_code == 404


def test_delete_requires_admin(client, db):
    wo = _mk_wo(db)
    r = client.delete(f"/api/work-orders/{wo.id}", headers=_executor_headers(db))
    assert r.status_code == 403
    # 未被删掉
    assert client.get(f"/api/work-orders/{wo.id}", headers=_executor_headers(db)).status_code == 200


def test_delete_cleans_non_cascade_refs(client_auth, db):
    wo = _mk_wo(db)
    wid = wo.id
    # 其它工单把它当作「触发新工单」
    other = _mk_wo(db)
    db.get(WorkOrder, other.id).triggered_wo_id = wid
    # 数据池记录引用它
    pool = DataPoolItem(pool_type="plan", title="池引用该工单", work_order_id=wid)
    db.add(pool)
    db.commit()

    r = client_auth.delete(f"/api/work-orders/{wid}")
    assert r.status_code == 200

    db.expire_all()
    assert db.get(WorkOrder, wid) is None
    assert db.get(WorkOrder, other.id).triggered_wo_id is None
    assert db.get(DataPoolItem, pool.id).work_order_id is None


def test_delete_blocked_when_live_oa(client_auth, db):
    """已发起真实钉钉 OA 审批（oa_id 非本地 OA- 占位）的工单不允许删除。"""
    wo = _mk_wo(db)
    entity = db.get(WorkOrder, wo.id)
    entity.oa_id = "real-oa-instance-002"
    db.commit()

    r = client_auth.delete(f"/api/work-orders/{wo.id}")
    assert r.status_code == 409
    # 未被删掉
    assert db.get(WorkOrder, wo.id) is not None


def test_delete_allowed_with_local_placeholder_oa(client_auth, db):
    """本地占位 OA 单号（未真正发起）仍可删除——「未发起」的边界口径。"""
    wo = _mk_wo(db)
    entity = db.get(WorkOrder, wo.id)
    entity.oa_id = "OA-20260914-001"
    db.commit()

    r = client_auth.delete(f"/api/work-orders/{wo.id}")
    assert r.status_code == 200
    db.expire_all()
    assert db.get(WorkOrder, wo.id) is None