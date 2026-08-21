"""配置 CRUD + dashboard 统计 测试（通过 TestClient）"""
from app.api.admin import clear_transactional_data


def test_dashboard_stats(client):
    r = client.get("/api/dashboard/stats")
    assert r.status_code == 200
    d = r.json()
    assert "total" in d
    assert "source_dist" in d
    assert "overdue_items" in d


def test_config_sources(client):
    r = client.get("/api/config/sources")
    assert r.status_code == 200
    assert len(r.json()) >= 4  # plan/alert/meeting/manual


def test_config_parsing_rules_crud(client):
    # 新增
    r = client.post("/api/config/parsing-rules", json={"name": "测试规则X", "pattern": "测试X", "weight": 3})
    assert r.status_code == 201
    rid = r.json()["id"]
    # 改权重
    r2 = client.patch(f"/api/config/parsing-rules/{rid}?weight=5")
    assert r2.json()["weight"] == 5
    # 删除
    r3 = client.delete(f"/api/config/parsing-rules/{rid}")
    assert r3.status_code == 204


def test_work_order_type_crud(client):
    r = client.post("/api/config/work-order-types", json={"type_code": "tt", "name": "测试类型", "default_priority": "P3"})
    assert r.status_code == 201
    tid = r.json()["id"]
    client.delete(f"/api/config/work-order-types/{tid}")


def test_sla_update(client):
    r = client.get("/api/config/sla")
    p1 = next(s for s in r.json() if s["priority"] == "P1")
    r2 = client.patch(f"/api/config/sla/{p1['id']}", json={"deadline_days": 2})
    assert r2.json()["deadline_days"] == 2


def test_parse_minutes_api(client):
    r = client.post("/api/import/parse-minutes", json={"text": "1. 通辽永兴变桨排查 王小宁 8月15日前"})
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_clear_data(client, db):
    """清空事务数据，配置保留"""
    r = client.delete("/api/admin/clear-data")
    assert r.status_code == 200
    cleared = r.json()["cleared"]
    assert "work_orders" in cleared
    # 工单清零
    from app.models import WorkOrder, WorkOrderTypeKB
    assert db.query(WorkOrder).count() == 0
    # 类型保留
    assert db.query(WorkOrderTypeKB).count() > 0


def test_oa_callback_advances_by_chain(client, db):
    """钉钉 OA 回调按角色链逐节点推进：dispatched → verifying → closed"""
    from datetime import date
    from app.api.workorders import create_work_order
    from app.schemas.workorder import WorkOrderCreate
    from app.models import WorkOrder

    wo = create_work_order(WorkOrderCreate(
        title="OA回调测试", action="做", source_code="manual", priority="P2",
        deadline=date.today(), project_id=1, person_id=1, approver_id=11,
    ), db)
    payload = {
        "processInstanceId": "PI-TEST-001",
        "result": "agree",
        "activityName": "审批",
        "formComponentValues": [{"name": "工单编号", "value": wo.code}],
    }
    r1 = client.post("/api/dingtalk/oa/callback", json=payload)
    assert r1.json()["status"] == "dispatched"
    r2 = client.post("/api/dingtalk/oa/callback", json=payload)
    assert r2.json()["status"] == "verifying"
    r3 = client.post("/api/dingtalk/oa/callback", json=payload)
    assert r3.json()["status"] == "closed"

    orm = db.get(WorkOrder, wo.id)
    assert orm.completed_date is not None
    assert orm.oa_id == "PI-TEST-001"


def test_oa_callback_refuse(client, db):
    """任意节点驳回 → rejected"""
    from datetime import date
    from app.api.workorders import create_work_order
    from app.schemas.workorder import WorkOrderCreate

    wo = create_work_order(WorkOrderCreate(
        title="OA驳回测试", action="做", source_code="manual", priority="P2",
        deadline=date.today(), project_id=1, person_id=1, approver_id=11,
    ), db)
    payload = {
        "processInstanceId": "PI-TEST-002",
        "result": "refuse",
        "activityName": "审批",
        "formComponentValues": [{"name": "工单编号", "value": wo.code}],
    }
    r = client.post("/api/dingtalk/oa/callback", json=payload)
    assert r.json()["status"] == "rejected"
