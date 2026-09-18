"""用户管理的组织资料、业务岗位和通知规则回归。"""
from app.models import BusinessRoleAssignment, User


def test_user_list_returns_dingtalk_department_and_business_roles(client_auth, db):
    user = db.query(User).filter(User.role == "executor").first()
    user.department = "钉钉运检部"
    db.commit()

    response = client_auth.get("/api/auth/users", params={"q": user.name})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["department"] == "钉钉运检部"
    assert item["business_roles"] == [{"code": "project_member", "name": "项目人员", "is_default": True}]


def test_user_profile_and_business_roles_are_saved_as_one_user_configuration(client_auth, db):
    user = db.query(User).filter(User.role == "executor").first()

    profile = client_auth.patch(f"/api/auth/users/{user.id}/profile", json={"department": "华北区域"})
    roles = client_auth.put(
        f"/api/auth/users/{user.id}/business-roles",
        json={"role_codes": ["pmo", "regional_pmo"]},
    )

    assert profile.status_code == 200
    assert roles.status_code == 200
    assert {role["code"] for role in roles.json()["business_roles"]} == {"pmo", "regional_pmo"}
    assert db.get(User, user.id).department == "华北区域"
    assert db.query(BusinessRoleAssignment).filter_by(user_id=user.id).count() == 2


def test_project_group_sync_and_candidates_are_retired(client_auth):
    assert client_auth.post("/api/organization/projects/1/sync-preview").status_code == 404
    assert client_auth.post("/api/organization/projects/1/sync-candidates").status_code == 404
    assert client_auth.get("/api/organization/sync-candidates").status_code == 404
    assert client_auth.get("/api/config/region-pmos").status_code == 404
    assert client_auth.get("/api/config/role-assignments").status_code == 404
    assert client_auth.get("/api/config/notification-policies").status_code == 404


def test_notification_rules_restrict_channels_and_preview_is_safe(client_auth, db):
    bad = client_auth.post("/api/organization/notification-rules", json={"name": "bad", "event": "dispatch", "channels": ["sms"]})
    assert bad.status_code == 400
    user = db.query(User).filter(User.role == "executor").first()
    invalid_event = client_auth.post("/api/organization/notification-rules", json={"name": "bad event", "event": "later", "channels": ["robot_private"], "recipients": {"user_ids": [user.id]}})
    assert invalid_event.status_code == 400
    good = client_auth.post("/api/organization/notification-rules", json={"name": "私聊草稿", "event": "dispatch", "channels": ["robot_private"], "recipients": {"user_ids": [user.id], "responsible": True}, "enabled": True})
    assert good.status_code == 201
    assert good.json()["recipients"]["user_ids"] == [user.id]
    from app.models import WorkOrder
    wo = db.query(WorkOrder).first()
    preview = client_auth.post(f"/api/organization/notification-rules/{good.json()['id']}/preview", params={"work_order_id": wo.id})
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True


def test_operation_events_are_admin_only(client, auth_headers):
    assert client.get("/api/organization/operation-events").status_code == 401
    assert client.get("/api/organization/operation-events", headers=auth_headers).status_code == 200
