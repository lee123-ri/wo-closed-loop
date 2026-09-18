"""服务探针回归。"""

from fastapi.testclient import TestClient

from app.main import app


def test_readiness_probe_checks_database_connection():
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] == "ok"
