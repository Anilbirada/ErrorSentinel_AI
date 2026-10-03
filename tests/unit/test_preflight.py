from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import api
from app.config import Settings


def test_incomplete_graph_configuration_is_reported_without_values(
    monkeypatch,
) -> None:
    secret = "test-secret-must-never-be-returned"
    settings = Settings(
        _env_file=None,
        ms_tenant_id="test-tenant",
        ms_client_id="test-client",
        ms_client_secret=secret,
        monitor_mailbox="monitor@example.test",
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(api.router)

    with TestClient(app) as client:
        health = client.get("/api/health")
        preflight = client.get("/api/preflight")
        run = client.post("/api/run-now")

    assert health.status_code == 200
    assert health.json() == {
        "status": "healthy",
        "service": "RSR ErrorSentinel AI",
    }
    assert preflight.status_code == 200
    assert preflight.json() == {
        "status": "incomplete",
        "missing": ["ALERT_FROM_MAILBOX", "ALERT_RECIPIENTS"],
    }
    assert run.status_code == 503
    assert run.json()["detail"]["missing"] == [
        "ALERT_FROM_MAILBOX",
        "ALERT_RECIPIENTS",
    ]
    assert secret not in health.text + preflight.text + run.text


def test_complete_graph_preflight_discloses_no_configuration_values(
    monkeypatch,
) -> None:
    secret = "test-secret-must-never-be-returned"
    settings = Settings(
        _env_file=None,
        ms_tenant_id="test-tenant",
        ms_client_id="test-client",
        ms_client_secret=secret,
        monitor_mailbox="monitor@example.test",
        alert_from_mailbox="sender@example.test",
        alert_recipients="recipient@example.test",
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(api.router)

    with TestClient(app) as client:
        response = client.get("/api/preflight")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "missing": []}
    assert secret not in response.text
