from fastapi.testclient import TestClient

from fringepay.main import app

client = TestClient(app)


def test_health_endpoint_reports_process_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fringepay"}


def test_status_endpoint_is_explicitly_sandbox_only() -> None:
    response = client.get("/v1/status")

    assert response.status_code == 200
    assert response.json()["mode"] == "sandbox-only"
