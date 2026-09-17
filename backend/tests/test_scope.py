"""行级数据范围回归：「我的工单」（scope=mine）按登录人身份过滤。

背景（2026-09-15）：我的工单页原先带「切换人员」下拉、按 person_name 查，
普通执行人能切到任意他人/全部工单；且没有按角色收口。修复后：

- admin        → scope=mine 等于全量（不过滤）
- 区域 PMO      → 只看其负责区域（region_pmos）的工单
- 其他(executor) → 只看本人相关（责任人 person_id 或审批人 approver_id）

对 /work-orders?scope=mine 与 /dashboard/mine 两个入口验证。
"""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.api.workorders import create_work_order
from app.models import RegionPMO, User, WorkOrder
from app.schemas.workorder import WorkOrderCreate


def _mk(db, title, person_id=None, approver_id=None, region=None):
    return create_work_order(WorkOrderCreate(
        title=title, action="做", reason="测", source_code="manual",
        priority="P2", deadline=date.today(), project_id=1,
        person_id=person_id, approver_id=approver_id, type_id=1,
        planned_start_date=date.today(), region=region,
    ), db)


def _token_headers(db, user):
    from app.core.security import create_access_token
    token = create_access_token(str(user.id), extra={"name": user.name, "role": user.role})
    return {"Authorization": f"Bearer {token}"}


def _client_with(db, user):
    c = TestClient(app)
    c.headers.update(_token_headers(db, user))
    return c


def _codes(r):
    return {w["code"] for w in r.json()["items"]}


def test_admin_scope_mine_sees_all(client_auth):
    """admin 的 scope=mine 不附加过滤，总量与不带 scope 一致。"""
    full = client_auth.get("/api/work-orders", params={"page_size": 100}).json()["total"]
    mine = client_auth.get("/api/work-orders", params={"scope": "mine", "page_size": 100}).json()["total"]
    assert mine == full


def test_executor_scope_mine_only_related(db):
    """普通执行人 scope=mine 只看自己作为责任人/审批人的工单，看不到他人的。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()

    mine_person = _mk(db, "s-责任人本人", person_id=me.id, approver_id=other.id)
    mine_approver = _mk(db, "s-审批人本人", person_id=other.id, approver_id=me.id)
    someone_else = _mk(db, "s-他人", person_id=other.id, approver_id=other.id)

    r = _client_with(db, me).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    assert r.status_code == 200
    codes = _codes(r)
    assert mine_person.code in codes
    assert mine_approver.code in codes
    assert someone_else.code not in codes


def test_region_pmo_scope_mine_only_region(db):
    """区域 PMO 的 scope=mine 只看其负责区域 + 本人相关；区分区域外的他人工单不出现。"""
    pmo = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != pmo.id).first()

    db.add(RegionPMO(region="华东", user_id=pmo.id))
    db.flush()

    in_region = _mk(db, "r-区内", person_id=other.id, approver_id=other.id, region="华东")
    out_region = _mk(db, "r-区外", person_id=other.id, approver_id=other.id, region="华北")

    r = _client_with(db, pmo).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    assert r.status_code == 200
    codes = _codes(r)
    assert in_region.code in codes
    assert out_region.code not in codes


def test_region_pmo_also_sees_own_cross_region(db):
    """区域 PMO 自己作为责任人的跨区域工单也要出现（region + self 并集）。"""
    pmo = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != pmo.id).first()

    db.add(RegionPMO(region="华东", user_id=pmo.id))
    db.flush()

    own_cross = _mk(db, "r-本人跨区", person_id=pmo.id, approver_id=other.id, region="华北")

    r = _client_with(db, pmo).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    assert r.status_code == 200
    assert own_cross.code in _codes(r)


def test_closed_list_scope_mine(db):
    """闭环记录 scope=mine 同样按行级范围收口。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()

    mine_closed = _mk(db, "c-本人closed", person_id=me.id, approver_id=other.id)
    other_closed = _mk(db, "c-他人closed", person_id=other.id, approver_id=other.id)
    for code in (mine_closed.code, other_closed.code):
        orm = db.query(WorkOrder).filter(WorkOrder.code == code).first()
        orm.status = "closed"
        orm.completed_date = date.today()
    db.flush()

    r = _client_with(db, me).get("/api/work-orders/closed/list", params={"scope": "mine", "page_size": 100})
    assert r.status_code == 200
    codes = _codes(r)
    assert mine_closed.code in codes
    assert other_closed.code not in codes


def test_my_dashboard_mine_stats_scope_self(db):
    """/dashboard/mine 按当前人行级范围聚合，普通执行人 scope=self。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()
    _mk(db, "d-本人", person_id=me.id, approver_id=other.id)

    r = _client_with(db, me).get("/api/dashboard/mine")
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "self"
    assert body["stats"]["total"] >= 1


def test_my_dashboard_mine_stats_scope_region(db):
    """/dashboard/mine 对区域 PMO 返回 scope=region。"""
    pmo = db.query(User).filter(User.role == "executor").first()
    db.add(RegionPMO(region="华东", user_id=pmo.id))
    db.flush()

    r = _client_with(db, pmo).get("/api/dashboard/mine")
    assert r.status_code == 200
    assert r.json()["scope"] == "region"