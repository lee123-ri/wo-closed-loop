"""数据范围角色可配置性回归：admin 锁定、事业部 PMO、区域 PMO、普通成员，以及范围改动生效。

背景（2026-09-17）：数据范围从 scope.py 硬编码改为 role_data_scopes 后台可配，
admin 锁死「全部」，事业部 PMO 默认「全部」（可改），区域 PMO 默认「自己相关+区域」（可改），
普通成员默认「自己相关」（可改）；多选取并集。
"""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.api.workorders import create_work_order
from app.models import RegionPMO, RoleAssignment, RoleDataScope, User
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


# ── admin 锁定 ──────────────────────────────────────────

def test_admin_role_scope_is_locked(client_auth):
    rows = client_auth.get("/api/config/role-scopes").json()
    admin = next(r for r in rows if r["role_code"] == "admin")
    assert admin["is_locked"] is True
    assert admin["scopes"] == ["all"]


def test_admin_role_scope_cannot_be_updated(client_auth):
    r = client_auth.put("/api/config/role-scopes/admin", json={"scopes": ["self"]})
    assert r.status_code == 400


# ── 事业部 PMO 看全部 ───────────────────────────────────

def test_division_pmo_scope_mine_sees_all(db):
    """事业部 PMO（role_assignments.pmo）默认看全部，不因非本人/非区域被收窄。"""
    ra = db.query(RoleAssignment).filter(RoleAssignment.role_code == "pmo").first()
    pmo = db.get(User, ra.user_id)
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
    db.add(RegionPMO(region="华东", user_id=pmo.id))
    _role_row(db, "region_pmo").scopes = ["region"]
    db.flush()

    in_region = _mk(db, "rs-区内他人", person_id=other.id, approver_id=other.id, region="华东")
    own_cross = _mk(db, "rs-本人跨区", person_id=pmo.id, approver_id=other.id, region="华北")

    r = _client_with(db, pmo).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    codes = _codes(r)
    assert in_region.code in codes       # 区域范围仍生效
    assert own_cross.code not in codes   # self 被去掉后不再兜底本人


def test_member_can_be_granted_all(db):
    """普通成员配置为 all 后能看全部。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()
    _role_row(db, "member").scopes = ["all"]
    db.flush()

    other_wo = _mk(db, "m-他人", person_id=other.id, approver_id=other.id)
    r = _client_with(db, me).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    assert other_wo.code in _codes(r)


def test_empty_scopes_means_nothing(db):
    """勾选为空集时显式无范围，不误放量成「全部」。"""
    me = db.query(User).filter(User.role == "executor").first()
    other = db.query(User).filter(User.role == "executor", User.id != me.id).first()
    _role_row(db, "member").scopes = []
    db.flush()

    mine_wo = _mk(db, "e-本人", person_id=me.id, approver_id=other.id)
    r = _client_with(db, me).get("/api/work-orders", params={"scope": "mine", "page_size": 100})
    assert mine_wo.code not in _codes(r)


# ── API 校验 ───────────────────────────────────────────

def test_role_scope_update_validates_values(client_auth):
    r = client_auth.put("/api/config/role-scopes/member", json={"scopes": ["self", "bogus"]})
    assert r.status_code == 400


def test_role_scope_update_ok(client_auth):
    r = client_auth.put("/api/config/role-scopes/member", json={"scopes": ["self", "region"]})
    assert r.status_code == 200
    assert set(r.json()["scopes"]) == {"self", "region"}


def test_role_scope_unknown_role(client_auth):
    r = client_auth.put("/api/config/role-scopes/no_such_role", json={"scopes": ["self"]})
    assert r.status_code == 404