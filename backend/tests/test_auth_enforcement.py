"""鉴权强制收编测试：业务路由无 token 401 / 越权 403 / 豁免端点放行 / 钉钉管理员登录"""
from fastapi.testclient import TestClient

from app.main import app


def _executor_headers(db):
    from app.models import User
    from app.core.security import create_access_token
    u = db.query(User).filter(User.role == "executor").first()
    token = create_access_token(str(u.id), extra={"name": u.name, "role": u.role})
    return {"Authorization": f"Bearer {token}"}


def test_business_routes_require_auth(client):
    """业务接口未登录一律 401"""
    for path in ("/api/work-orders", "/api/dashboard/stats", "/api/pool/items",
                 "/api/config/sources", "/api/dingtalk/status"):
        r = client.get(path)
        assert r.status_code == 401, f"{path} 应 401，实际 {r.status_code}"
    r = client.post("/api/pool/generate-all")
    assert r.status_code == 401


def test_admin_routes_require_admin(client, db):
    """executor 调管理员接口应 403"""
    r = client.delete("/api/admin/clear-data", headers=_executor_headers(db))
    assert r.status_code == 403


def test_public_endpoints_open(client):
    """豁免端点不需要 token"""
    assert client.get("/health").status_code == 200
    assert client.get("/api/auth/permissions").status_code == 200


# ── 菜单权限配置：持久化 + 管理员独占 ─────────────────

def test_get_permissions_defaults(client):
    """默认权限返回 4 角色 + 用户管理仅 admin"""
    body = client.get("/api/auth/permissions").json()
    assert body["roles"] == ["admin", "approver", "executor", "readonly"]
    assert body["menu_groups"]["基础数据"]["用户管理"]["roles"] == ["admin"]


def test_save_permissions_requires_admin(client, db):
    """非管理员改菜单权限应 403"""
    r = client.put("/api/auth/permissions", json={"menu_groups": {}}, headers=_executor_headers(db))
    assert r.status_code == 403


def test_save_and_reload_permissions(client, auth_headers):
    """管理员保存后 GET 能读到，未提交的 actions 保留默认"""
    cur = client.get("/api/auth/permissions").json()
    cur["menu_groups"]["基础数据"]["用户管理"]["roles"] = ["admin", "approver"]
    r = client.put("/api/auth/permissions", json={"menu_groups": cur["menu_groups"]}, headers=auth_headers)
    assert r.status_code == 200

    body = client.get("/api/auth/permissions").json()
    assert body["menu_groups"]["基础数据"]["用户管理"]["roles"] == ["admin", "approver"]
    assert body["actions"]["manage_users"]["roles"] == ["admin"]


def test_save_permissions_rejects_bad_role(client, auth_headers):
    """非法角色值应 400"""
    r = client.put("/api/auth/permissions",
                   json={"menu_groups": {"基础数据": {"用户管理": {"roles": ["superuser"]}}}},
                   headers=auth_headers)
    assert r.status_code == 400


# ── 姓名登录：默认关闭 ────────────────────────────────

def test_name_login_disabled_by_default(client):
    """姓名登录默认停用 → 403"""
    r = client.post("/api/auth/name", json={"name": "李沛东"})
    assert r.status_code == 403


def test_name_login_works_when_enabled(client, monkeypatch):
    """显式开启后姓名登录可用（内部应急通道）"""
    from app.api import auth as auth_api
    monkeypatch.setattr(auth_api.settings, "name_login_enabled", True)

    r = client.post("/api/auth/name", json={"name": "李沛东"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["user"]["role"] == "admin"

    assert client.post("/api/auth/name", json={"name": "不存在的人"}).status_code == 401
    assert client.post("/api/auth/name", json={"name": "   "}).status_code == 400


# ── 开发登录：默认关闭，生产恒关 ──────────────────────

def test_dev_login_disabled_by_default(client, monkeypatch):
    """开发登录默认停用 → 403（不读环境 .env，强制默认值，避免本机 DEV_LOGIN_ENABLED=true 干扰）"""
    from app.api import auth as auth_api
    monkeypatch.setattr(auth_api.settings, "dev_login_enabled", False)
    r = client.post("/api/auth/dev-login", json={"user_id": 999, "name": "x", "role": "admin"})
    assert r.status_code == 403


def test_dev_login_blocked_in_prod(client, monkeypatch):
    """生产环境即使开启开关也拒绝"""
    from app.api import auth as auth_api
    monkeypatch.setattr(auth_api.settings, "app_env", "production")
    monkeypatch.setattr(auth_api.settings, "dev_login_enabled", True)
    r = client.post("/api/auth/dev-login", json={"user_id": 999, "name": "x", "role": "admin"})
    assert r.status_code == 403


# ── 钉钉 OAuth：仅管理员、不自动建号 ─────────────────

class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _mock_dingtalk(monkeypatch, union_id, nick, mobile=""):
    """打桩钉钉接口：code 换 token + 拉用户信息"""
    import app.api.auth as auth_api
    monkeypatch.setattr(auth_api.settings, "dingtalk_app_key", "testkey")
    monkeypatch.setattr(auth_api.httpx, "post",
                        lambda url, **kw: _Resp({"accessToken": "fake-token", "refreshToken": "r"}))
    monkeypatch.setattr(auth_api.httpx, "get",
                        lambda url, **kw: _Resp({"unionId": union_id, "nick": nick, "mobile": mobile}))


def test_dingtalk_login_binds_admin(client, db, monkeypatch):
    """已存在的管理员首次钉钉登录 → 绑定 union_id 并放行"""
    from app.models import User
    _mock_dingtalk(monkeypatch, union_id="union_admin_1", nick="李沛东")

    before = db.query(User).count()
    r = client.get("/api/auth/dingtalk/callback", params={"code": "abc"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"
    # 不自动建号：用户数不变
    assert db.query(User).count() == before
    # union_id 已绑定
    admin = db.query(User).filter(User.name == "李沛东").first()
    assert admin.dingtalk_id == "union_admin_1"


def test_dingtalk_login_bound_admin_repeat(client, db, monkeypatch):
    """已绑定管理员二次登录直接放行"""
    from app.models import User
    admin = db.query(User).filter(User.role == "admin").first()
    admin.dingtalk_id = "union_admin_2"
    db.commit()

    _mock_dingtalk(monkeypatch, union_id="union_admin_2", nick="李沛东")
    r = client.get("/api/auth/dingtalk/callback", params={"code": "abc"})
    assert r.status_code == 200
    assert r.json()["user"]["id"] == admin.id


def test_dingtalk_login_rejects_non_admin(client, db, monkeypatch):
    """非管理员（即使是系统内用户）钉钉登录被拒 403"""
    from app.models import User
    _mock_dingtalk(monkeypatch, union_id="union_exec_1", nick="王小宁")

    before = db.query(User).count()
    r = client.get("/api/auth/dingtalk/callback", params={"code": "abc"})
    assert r.status_code == 403
    assert db.query(User).count() == before


def test_dingtalk_login_rejects_unknown_user(client, db, monkeypatch):
    """系统外陌生钉钉用户被拒，且不自动建号"""
    from app.models import User
    _mock_dingtalk(monkeypatch, union_id="union_stranger", nick="路人甲")

    before = db.query(User).count()
    r = client.get("/api/auth/dingtalk/callback", params={"code": "abc"})
    assert r.status_code == 403
    assert db.query(User).count() == before
