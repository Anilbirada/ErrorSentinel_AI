from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import api as api_routes
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database.models import AlertDelivery, ErrorRegistryEntry, MonitoringRun
from app.database.session import Base as DatabaseBase
from app.services import RunService
from app.registry.txt_registry import TxtRegistry


class FakeGraphClient:
    instances = 0
    send_attempts = 0
    failure_message = "Simulated Graph send failure"

    def __init__(self, settings: Settings) -> None:
        self.instance_number = type(self).instances
        type(self).instances += 1

    async def messages_since(self, received_after: str | None) -> AsyncIterator[dict]:
        if self.instance_number == 0:
            yield {
                "id": "message-1",
                "receivedDateTime": "2026-01-01T00:00:00Z",
                "subject": "Failure: ERR-9001",
                "from": {"emailAddress": {"address": "sender@example.test"}},
                "body": {"content": "The operation failed with ERR-9001"},
                "hasAttachments": True,
            }

    async def attachments(self, message_id: str) -> list[dict]:
        raise AssertionError("Attachments should remain disabled")

    async def send_mail(self, subject: str, html: str) -> None:
        type(self).send_attempts += 1
        if type(self).send_attempts == 1:
            raise RuntimeError(type(self).failure_message)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_failed_alert_is_retried_without_rescanning_mail(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    FakeGraphClient.instances = 0
    FakeGraphClient.send_attempts = 0
    FakeGraphClient.failure_message = "sensitive-exception-text-must-not-be-logged"
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    DatabaseBase.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.services.SessionLocal", test_sessions)
    monkeypatch.setattr("app.services.GraphClient", FakeGraphClient)
    settings = Settings(
        _env_file=None,
        registry_file=tmp_path / "data" / "codes.txt",
        reports_dir=tmp_path / "reports",
        downloads_dir=tmp_path / "downloads",
        ms_tenant_id="test-tenant",
        ms_client_id="test-client",
        ms_client_secret="secret-that-must-not-be-logged",
        monitor_mailbox="monitor@example.test",
        alert_from_mailbox="sender@example.test",
        alert_recipients="recipient@example.test",
    )
    monkeypatch.setattr(api_routes, "SessionLocal", test_sessions)
    monkeypatch.setattr(api_routes, "get_settings", lambda: settings)
    service = RunService(settings)

    first_run_id = await service.run()
    with test_sessions() as db:
        first_run = db.get(MonitoringRun, first_run_id)
        assert first_run is not None and first_run.status == "PARTIAL"
        assert db.scalars(select(ErrorRegistryEntry.code)).all() == []
        assert db.scalar(select(AlertDelivery.status)) == "FAILED"
    assert not TxtRegistry(settings.registry_file).exists("ERR-9001")
    assert "secret-that-must-not-be-logged" not in caplog.text
    assert FakeGraphClient.failure_message not in caplog.text
    app = FastAPI()
    app.include_router(api_routes.router)
    with TestClient(app) as client:
        failed_deliveries = client.get(
            f"/api/runs/{first_run_id}/deliveries"
        ).json()
        unregistered_after_failure = client.get("/api/errors/new").json()

    second_run_id = await service.run()
    with test_sessions() as db:
        second_run = db.get(MonitoringRun, second_run_id)
        assert second_run is not None and second_run.status == "SUCCESS"
        assert db.scalars(select(ErrorRegistryEntry.code)).all() == ["ERR-9001"]
        assert set(db.scalars(select(AlertDelivery.status)).all()) == {
            "FAILED",
            "SUCCESS",
        }
    assert TxtRegistry(settings.registry_file).exists("ERR-9001")
    assert FakeGraphClient.send_attempts == 2

    with TestClient(app) as client:
        successful_deliveries = client.get(
            f"/api/runs/{second_run_id}/deliveries"
        ).json()
        unregistered_after_success = client.get("/api/errors/new").json()
    assert failed_deliveries == [
        {"status": "FAILED", "sent_at": None, "error": "RuntimeError"}
    ]
    assert successful_deliveries[0]["status"] == "SUCCESS"
    assert any(item["code"] == "ERR-9001" for item in unregistered_after_failure)
    assert all(item["code"] != "ERR-9001" for item in unregistered_after_success)
    engine.dispose()
