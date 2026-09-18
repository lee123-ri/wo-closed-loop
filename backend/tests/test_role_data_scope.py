"""业务岗位的数据范围可配置性回归。"""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.api.workorders import create_work_order
from app.models import BusinessRole, BusinessRoleAssignment, RegionPMO, RoleDataScope, User
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


def _role_row(db, role_code):
    return db.query(RoleDataScope).filter(RoleDataScope.role_code == role_code).first()


def _assign_business_role(db, user, role_code):
    role = db.query(BusinessRole).filter(BusinessRole.code == role_code).first()
    db.add(BusinessRoleAssignment(user_id=user.id, business_role_id=role.id, scope_type="global", source="manual"))
    db.flush()


# ── 业务岗位配置 ────────────────────────────────────────

def test_business_role_scopes_are_exposed(client_auth):
    rows = client_auth.get("/api/config/role-scopes").json()
    pmo = next(r for r in rows if r["role_code"] == "pmo")
    assert pmo["is_locked"] is False
    assert pmo["scopes"] == ["all"]


def test_system_role_is_not_a_business_scope(client_auth):
    r = client_auth.put("/api/config/role-scopes/admin", json={"scopes": ["self"]})
    assert r.status_code == 404


# ── 事业部 PMO 看全部 ───────────────────────────────────

def test_pmo_business_role_scope_mine_sees_all(db):
    """用户分配 PMO 业务岗位后，数据范围直接由该岗位配置决定。"""
    pmo = db.query(User).filter(User.role == "executor").first()
    _assign_business_role(db, pmo, "pmo")
    other = db.query(User).filter(User.role == "executor").first()
    wo = _mk(db, "d-事业部他人工单", person_id=other.id, approver_id=other.id, region="华南")

    r = _client_with(db, pmo).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    assert r.status_code == 200
    assert wo.code in _codes(r)


# ── 配置改动生效 ────────────────────────────────────────

def test_region_pmo_drop_self_scope(db):
    """区域 PMO 去掉「自己相关」后，本人跨区工单不再出现（self 不再是隐式下限）。"""
    pmo = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != pmo.id).first()
    _assign_business_role(db, pmo, "regional_pmo")
    db.add(RegionPMO(region="华东", user_id=pmo.id))
    _role_row(db, "regional_pmo").scopes = ["region"]
    db.flush()

    in_region = _mk(db, "rs-区内他人", person_id=other.id, approver_id=other.id, region="华东")
    own_cross = _mk(db, "rs-本人跨区", person_id=pmo.id, approver_id=other.id, region="华北")

    r = _client_with(db, pmo).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    codes = _codes(r)
    assert in_region.code in codes       # 区域范围仍生效
    assert own_cross.code not in codes   # self 被去掉后不再兜底本人


def test_business_role_can_be_granted_all(db):
    """场站人员岗位配置为 all 后能看全部。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()
    _assign_business_role(db, me, "site_member")
    _role_row(db, "site_member").scopes = ["all"]
    db.flush()

    other_wo = _mk(db, "m-他人", person_id=other.id, approver_id=other.id)
    r = _client_with(db, me).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    assert other_wo.code in _codes(r)


def test_empty_scopes_means_nothing(db):
    """勾选为空集时显式无范围，不误放量成「全部」。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()
    _assign_business_role(db, me, "site_member")
    _role_row(db, "site_member").scopes = []
    db.flush()

    mine_wo = _mk(db, "e-本人", person_id=me.id, approver_id=other.id)
    r = _client_with(db, me).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    assert mine_wo.code not in _codes(r)


# ── API 校验 ───────────────────────────────────────────

def test_role_scope_update_validates_values(client_auth):
    r = client_auth.put("/api/config/role-scopes/site_member", json={"scopes": ["self", "bogus"]})
    assert r.status_code == 400


def test_role_scope_update_ok(client_auth):
    r = client_auth.put("/api/config/role-scopes/site_member", json={"scopes": ["self", "region"]})
    assert r.status_code == 200
    assert set(r.json()["scopes"]) == {"self", "region"}


def test_role_scope_unknown_role(client_auth):
    r = client_auth.put("/api/config/role-scopes/no_such_role", json={"scopes": ["self"]})
    assert r.status_code == 404
