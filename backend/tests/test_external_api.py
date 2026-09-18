"""外部建单 / 查询 API 回归（X-API-Key 通道）。

覆盖：API Key 鉴权（缺/错/未配置）、名称/编码解析（项目/责任人找不到即报错）、
必填校验、幂等去重、查询回传、优先级默认与非法拦截。
"""
import pytest

from app.core.config import get_settings
from app.models import Project, WorkOrder

TEST_KEY = "test-external-key-123456"


@pytest.fixture(autouse=True)
def _external_key_configured(monkeypatch):
    """测试默认启用外部接口：环境变量 EXTERNAL_API_KEY 钉死为 TEST_KEY。"""
    s = get_settings()
    monkeypatch.setattr(s, "external_api_key", TEST_KEY)


def _h(**overrides):
    headers = {"X-API-Key": TEST_KEY}
    headers.update(overrides)
    return headers


def _payload(**overrides):
    body = {
        "title": "外部测试工单",
        "project_name": "通辽永兴风电场",
        "person_name": "王小宁",
        "approver_name": "金惠良",
    }
    body.update(overrides)
    return body


# ── 鉴权 ──────────────────────────────────────────────

def test_missing_api_key_401(client):
    r = client.post("/api/external/work-orders", json=_payload())
    assert r.status_code == 401


def test_wrong_api_key_401(client):
    r = client.post("/api/external/work-orders", json=_payload(),
                    headers=_h(**{"X-API-Key": "wrong-key"}))
    assert r.status_code == 401


def test_not_configured_503(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "external_api_key", "")
    r = client.post("/api/external/work-orders", json=_payload(), headers=_h())
    assert r.status_code == 503


# ── 建单 ──────────────────────────────────────────────

def test_create_success(client):
    r = client.post("/api/external/work-orders", json=_payload(), headers=_h())
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["code"].startswith("RW-")
    assert data["status"] == "pending"          # 外部建单落「待派发」
    assert data["source_code"] == "meeting"    # 未传类型兜底「关键会议」
    assert data["project_name"] == "通辽永兴风电场"
    assert data["person_name"] == "王小宁"
    assert data["approver_name"] == "金惠良"
    assert data["title"] == "外部测试工单"


def test_create_by_project_code(client, db):
    p = db.query(Project).filter(Project.name == "通辽永兴风电场").first()
    assert p is not None
    r = client.post("/api/external/work-orders", json=_payload(project_code=p.code, project_name=None),
                    headers=_h())
    assert r.status_code == 201, r.text
    assert r.json()["project_name"] == "通辽永兴风电场"


def test_missing_project_422(client):
    r = client.post("/api/external/work-orders",
                    json=_payload(project_name=None, project_code=None), headers=_h())
    assert r.status_code == 422


def test_project_not_found_404(client):
    r = client.post("/api/external/work-orders",
                    json=_payload(project_name="不存在的项目"), headers=_h())
    assert r.status_code == 404


def test_person_not_found_404(client):
    r = client.post("/api/external/work-orders",
                    json=_payload(person_name="不存在的人"), headers=_h())
    assert r.status_code == 404


def test_alert_defaults_p1(client):
    r = client.post("/api/external/work-orders",
                    json=_payload(source_code="power_gen", priority=None), headers=_h())
    assert r.status_code == 201, r.text
    assert r.json()["priority"] == "P1"


def test_non_alert_defaults_p2(client):
    r = client.post("/api/external/work-orders",
                    json=_payload(source_code="meeting", priority=None), headers=_h())
    assert r.status_code == 201, r.text
    assert r.json()["priority"] == "P2"


def test_invalid_priority_422(client):
    r = client.post("/api/external/work-orders",
                    json=_payload(priority="XYZ"), headers=_h())
    assert r.status_code == 422


# ── 幂等 ──────────────────────────────────────────────

def test_idempotent_create(client, db):
    cid = "ext-abc-unique-001"
    r1 = client.post("/api/external/work-orders",
                     json=_payload(client_request_id=cid), headers=_h())
    assert r1.status_code == 201, r1.text
    wo1 = r1.json()

    r2 = client.post("/api/external/work-orders",
                     json=_payload(client_request_id=cid), headers=_h())
    assert r2.status_code == 200, r2.text   # 幂等命中返回 200 而非 201
    wo2 = r2.json()
    assert wo2["id"] == wo1["id"]
    assert wo2["code"] == wo1["code"]

    cnt = db.query(WorkOrder).filter(WorkOrder.client_request_id == cid).count()
    assert cnt == 1


# ── 查询 ──────────────────────────────────────────────

def _create(client, **overrides):
    r = client.post("/api/external/work-orders", json=_payload(**overrides), headers=_h())
    assert r.status_code == 201, r.text
    return r.json()


def test_query_by_code(client):
    wo = _create(client)
    r = client.get("/api/external/work-orders", params={"code": wo["code"]}, headers=_h())
    assert r.status_code == 200, r.text
    assert r.json()["id"] == wo["id"]
    assert r.json()["status"] == "pending"


def test_query_by_client_request_id(client):
    cid = "ext-query-001"
    wo = _create(client, client_request_id=cid)
    r = client.get("/api/external/work-orders", params={"client_request_id": cid}, headers=_h())
    assert r.status_code == 200, r.text
    assert r.json()["id"] == wo["id"]
    assert r.json()["client_request_id"] == cid


def test_query_missing_param_422(client):
    r = client.get("/api/external/work-orders", headers=_h())
    assert r.status_code == 422


def test_query_not_found_404(client):
    r = client.get("/api/external/work-orders", params={"code": "RW-2099-9999"}, headers=_h())
    assert r.status_code == 404