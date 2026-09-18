"""行级数据范围回归：管理范围与“我的工单”的严格个人范围。

背景（2026-09-15）：我的工单页原先带「切换人员」下拉、按 person_name 查，
普通执行人能切到任意他人/全部工单；且没有按角色收口。修复后：

- scope=mine   → 管理行级范围：admin 全量、区域 PMO 看负责区域、其他人看本人相关
- scope=personal 与 /dashboard/mine → 永远只看本人相关（责任人或审批人）

对 /work-orders 的两类范围、/dashboard/mine 与日历入口验证。
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


def test_my_dashboard_mine_stats_scope_personal(db):
    """/dashboard/mine 的普通执行人使用严格个人范围。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()
    _mk(db, "d-本人", person_id=me.id, approver_id=other.id)

    r = _client_with(db, me).get("/api/dashboard/mine")
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "personal"
    assert body["stats"]["total"] >= 1


def test_my_dashboard_mine_stats_scope_region_pmo_still_personal(db):
    """区域 PMO 的“我的工单”也不能扩展到区域范围。"""
    pmo = db.query(User).filter(User.role == "executor").first()
    db.add(RegionPMO(region="华东", user_id=pmo.id))
    db.flush()

    r = _client_with(db, pmo).get("/api/dashboard/mine")
    assert r.status_code == 200
    assert r.json()["scope"] == "personal"


def test_personal_scope_never_expands_for_admin_or_region_pmo(db):
    """“我的工单”是双角色个人视图，不能因管理身份扩大到全量或全区域。"""
    admin = db.query(User).filter(User.role == "admin").first()
    pmo = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != pmo.id).first()
    db.add(RegionPMO(region="华东", user_id=pmo.id))
    db.flush()

    admin_related = _mk(db, "personal-admin-related", person_id=admin.id, approver_id=other.id)
    admin_unrelated = _mk(db, "personal-admin-unrelated", person_id=other.id, approver_id=other.id)
    pmo_related = _mk(db, "personal-pmo-related", person_id=pmo.id, approver_id=other.id, region="华北")
    pmo_region_only = _mk(db, "personal-pmo-region-only", person_id=other.id, approver_id=other.id, region="华东")

    admin_codes = _codes(_client_with(db, admin).get("/api/work-orders", params={"scope": "personal", "page_size": 100}))
    assert admin_related.code in admin_codes
    assert admin_unrelated.code not in admin_codes

    pmo_codes = _codes(_client_with(db, pmo).get("/api/work-orders", params={"scope": "personal", "page_size": 100}))
    assert pmo_related.code in pmo_codes
    assert pmo_region_only.code not in pmo_codes


def test_my_dashboard_and_calendar_use_strict_personal_scope(db):
    """统计和日历必须与个人列表同口径；计划开始日也应作为日历事项返回。"""
    admin = db.query(User).filter(User.role == "admin").first()
    other = db.query(User).filter(User.role == "executor").first()
    related = _mk(db, "personal-calendar-related", person_id=admin.id, approver_id=other.id)
    unrelated = _mk(db, "personal-calendar-unrelated", person_id=other.id, approver_id=other.id)
    related.planned_start_date = date.today()
    related.deadline = date.today().replace(day=28) if date.today().day < 28 else date.today()
    unrelated.planned_start_date = date.today()
    unrelated.deadline = date.today()
    db.flush()

    client = _client_with(db, admin)
    dashboard = client.get("/api/dashboard/mine")
    assert dashboard.status_code == 200
    assert dashboard.json()["scope"] == "personal"
    calendar = client.get("/api/dashboard/calendar", params={"year": date.today().year, "month": date.today().month, "mine": True})
    assert calendar.status_code == 200
    codes = {item["code"] for item in calendar.json()["items"]}
    assert related.code in codes
    assert unrelated.code not in codes


def test_personal_scope_role_filter(db):
    """scope=personal 的 role 细分：responsible / approver / both 各只命中一种关联。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()

    r_person = _mk(db, "role-person", person_id=me.id, approver_id=other.id)
    r_approver = _mk(db, "role-approver", person_id=other.id, approver_id=me.id)
    r_both = _mk(db, "role-both", person_id=me.id, approver_id=me.id)

    c = _client_with(db, me)

    resp = c.get("/api/work-orders", params={"scope": "personal", "role": "responsible", "page_size": 100})
    codes = _codes(resp)
    assert r_person.code in codes
    assert r_both.code in codes  # 双角色同时是责任人
    assert r_approver.code not in codes

    resp = c.get("/api/work-orders", params={"scope": "personal", "role": "approver", "page_size": 100})
    codes = _codes(resp)
    assert r_approver.code in codes
    assert r_both.code in codes  # 双角色同时是审批人
    assert r_person.code not in codes

    resp = c.get("/api/work-orders", params={"scope": "personal", "role": "both", "page_size": 100})
    codes = _codes(resp)
    assert r_both.code in codes
    assert r_person.code not in codes
    assert r_approver.code not in codes
