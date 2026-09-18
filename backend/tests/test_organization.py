from app.models import BusinessRole, BusinessRoleAssignment, OrganizationSyncCandidate, User
from app.models.organization import OrganizationMappingRule
from app.services.organization import build_candidates_from_directory

def test_seeded_business_roles(db):
    assert {r.code for r in db.query(BusinessRole).all()} >= {"site_member", "project_manager", "regional_pmo", "headquarters_member"}

def test_candidate_confirmation_creates_assignment(client_auth, db):
    user = db.query(User).filter(User.role == "executor").first()
    response = client_auth.post("/api/organization/sync-candidates", json={"user_id": user.id, "business_role_code": "project_manager", "scope_type": "project", "scope_id": 1, "source_kind": "group", "source_value": "项目群", "confidence": 90})
    assert response.status_code == 201
    candidate_id = response.json()["id"]
    response = client_auth.post(f"/api/organization/sync-candidates/{candidate_id}/confirm")
    assert response.status_code == 200
    assert db.query(BusinessRoleAssignment).filter_by(user_id=user.id, scope_type="project", scope_id=1).count() == 1
    assert db.get(OrganizationSyncCandidate, candidate_id).status == "confirmed"


def test_notification_rules_restrict_channels_and_preview_is_safe(client_auth, db):
    bad = client_auth.post("/api/organization/notification-rules", json={"name":"bad","event":"dispatch","channels":["sms"]})
    assert bad.status_code == 400
    good = client_auth.post("/api/organization/notification-rules", json={"name":"私聊草稿","event":"dispatch","channels":["robot_private"],"recipients":{"responsible":True},"enabled":True})
    assert good.status_code == 201
    from app.models import WorkOrder
    wo = db.query(WorkOrder).first()
    preview = client_auth.post(f"/api/organization/notification-rules/{good.json()['id']}/preview", params={"work_order_id":wo.id})
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True


def test_operation_events_are_admin_only(client, auth_headers, db):
    assert client.get("/api/organization/operation-events").status_code == 401
    assert client.get("/api/organization/operation-events", headers=auth_headers).status_code == 200


def test_permission_role_can_grant_admin_access(client, db):
    admin = db.query(User).filter(User.role == "admin").first()
    executor = db.query(User).filter(User.role == "executor").first()
    create = client.post("/api/organization/permission-roles", headers={"Authorization": f"Bearer invalid"})
    assert create.status_code == 401
    from app.models import PermissionRole, UserPermissionRole
    role = PermissionRole(code="temporary_admin", name="临时管理员", data_scopes=["all"], menu_permissions=["*"], action_permissions=["*"])
    db.add(role); db.flush(); db.add(UserPermissionRole(user_id=executor.id, permission_role_id=role.id)); db.commit()
    from app.api.auth import has_permission_role
    assert has_permission_role(db, executor, "temporary_admin") is True
    assert admin.role == "admin"


def test_directory_mapping_only_creates_candidates_for_enabled_rules(db):
    rule = OrganizationMappingRule(name="项目经理", source_kind="title", pattern="项目经理", business_role_code="project_manager", scope_type="project", enabled=True)
    disabled = OrganizationMappingRule(name="停用", source_kind="department", pattern="总部", business_role_code="headquarters_member", scope_type="global", enabled=False)
    result = build_candidates_from_directory([{"user_id": 7, "title": "区域项目经理", "department": "总部"}], [rule, disabled])
    assert result == [{"user_id": 7, "business_role_code": "project_manager", "scope_type": "project", "scope_id": None, "source_kind": "title", "source_value": "区域项目经理", "confidence": 100}]


def test_legacy_notification_configuration_is_retired_and_audit_is_protected(client, client_auth):
    assert client.get("/api/config/audit-logs").status_code == 401
    assert client_auth.get("/api/config/notification-policies").status_code == 410
