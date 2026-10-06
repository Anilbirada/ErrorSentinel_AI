from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import api as api_routes
from app.api.routes import auth as auth_routes
from app.api.routes import connections as connection_routes
from app.auth import gmail_oauth
from app.config import Settings
from app.database.models import (
    AppUser,
    Base,
    ExtractedError,
    GmailConnection,
    GmailRegistryEntry,
    MonitoringRun,
)
from app.database import session as database_session
from app.registry.repository import RegistryRepository
from app.scheduler import scheduler as scheduler_module
from app.auth.gmail_oauth import decrypt_credentials, encrypt_credentials


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def test_existing_database_migration_adds_account_columns_and_indexes(monkeypatch):
    engine = create_engine("sqlite://")
    tables = (
        "monitoring_runs",
        "email_records",
        "attachment_records",
        "extracted_errors",
        "alert_deliveries",
        "jobs",
    )
    with engine.begin() as connection:
        for table in tables:
            connection.execute(
                text(f"CREATE TABLE {table} (id VARCHAR(64) PRIMARY KEY)")
            )
        connection.execute(
            text("INSERT INTO monitoring_runs (id) VALUES ('legacy-run')")
        )
    monkeypatch.setattr(database_session, "get_engine", lambda: engine)

    database_session.init_db()

    inspector = inspect(engine)
    for table in tables:
        columns = {column["name"] for column in inspector.get_columns(table)}
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        assert {"tenant_id", "gmail_connection_id"} <= columns
        assert f"ix_{table}_tenant_id" in indexes
        assert f"ix_{table}_gmail_connection_id" in indexes
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT id FROM monitoring_runs WHERE id = 'legacy-run'")
        ) == "legacy-run"
    engine.dispose()


def test_google_oauth_readiness_requires_strong_session_and_valid_encryption_keys():
    base_settings = {
        "google_client_id": "client-id",
        "google_client_secret": "client-secret",
        "google_redirect_uri": "http://localhost/auth/gmail/callback",
        "google_login_redirect_uri": "http://localhost/auth/google/callback",
        "session_secret_key": "s" * 32,
        "token_encryption_key": Fernet.generate_key().decode("ascii"),
    }

    assert Settings(_env_file=None, **base_settings).google_oauth_ready
    assert not Settings(
        _env_file=None,
        **{**base_settings, "session_secret_key": "short"},
    ).google_oauth_ready
    assert not Settings(
        _env_file=None,
        **{**base_settings, "token_encryption_key": "invalid"},
    ).google_oauth_ready


def test_oauth_state_is_browser_bound_single_use_and_expires(database):
    state = "oauth-state-value"
    with database() as db:
        gmail_oauth.save_oauth_state(
            db,
            state=state,
            browser_id="browser-a",
            purpose="connect",
            user_id="google-user-a",
        )
        with pytest.raises(HTTPException) as wrong_browser:
            gmail_oauth.consume_oauth_state(
                db,
                state=state,
                browser_id="browser-b",
                expected_purpose="connect",
            )
        assert wrong_browser.value.status_code == 400

        record = gmail_oauth.consume_oauth_state(
            db,
            state=state,
            browser_id="browser-a",
            expected_purpose="connect",
        )
        assert record.user_id == "google-user-a"
        with pytest.raises(HTTPException) as replay:
            gmail_oauth.consume_oauth_state(
                db,
                state=state,
                browser_id="browser-a",
                expected_purpose="connect",
            )
        assert replay.value.status_code == 400


def test_gmail_oauth_tokens_are_encrypted_at_rest():
    token_json = json.dumps(
        {
            "token": "access-token-test",
            "refresh_token": "refresh-token-test",
            "client_secret": "oauth-client-secret-test",
        }
    )
    settings = Settings(
        _env_file=None,
        token_encryption_key=Fernet.generate_key().decode("ascii"),
    )

    encrypted = encrypt_credentials(settings, token_json)

    assert token_json not in encrypted
    assert "access-token-test" not in encrypted
    assert decrypt_credentials(settings, encrypted) == token_json


def test_gmail_error_registries_are_isolated_per_connection(database, tmp_path):
    from app.models.extraction import ErrorRecord

    with database() as db:
        db.add_all(
            [
                AppUser(id="user-a", email="a@example.test"),
                AppUser(id="user-b", email="b@example.test"),
            ]
        )
        db.flush()
        account_a = GmailConnection(
            id="connection-a",
            user_id="user-a",
            email="a@example.test",
            encrypted_credentials="ciphertext-a",
        )
        account_b = GmailConnection(
            id="connection-b",
            user_id="user-b",
            email="b@example.test",
            encrypted_credentials="ciphertext-b",
        )
        db.add_all([account_a, account_b])
        db.commit()

        repo_a = RegistryRepository(db, connection_id=account_a.id)
        repo_b = RegistryRepository(db, connection_id=account_b.id)
        repo_a.commit_new_errors(
            [ErrorRecord(raw_code="ERR-9001", normalized_code="ERR-9001")],
            run_id="run-a",
            txt_path=tmp_path / "a" / "registry.txt",
        )

        assert repo_a.is_existing("ERR-9001")
        assert not repo_b.is_existing("ERR-9001")
        assert repo_b.decide("ERR-9001").value == "NEW"
        assert db.scalar(select(GmailRegistryEntry.code)) == "ERR-9001"


def test_connection_list_and_runs_are_scoped_to_signed_in_user(database, monkeypatch):
    with database() as db:
        for user_id, email, connection_id, run_id, code in (
            ("google-user-a", "a@example.test", "connection-a", "run-a", "ERR-1001"),
            ("google-user-b", "b@example.test", "connection-b", "run-b", "ERR-2002"),
        ):
            db.add(AppUser(id=user_id, email=email))
            db.flush()
            db.add(
                GmailConnection(
                    id=connection_id,
                    user_id=user_id,
                    email=email,
                    encrypted_credentials=f"cipher-{user_id}",
                )
            )
            db.add(
                MonitoringRun(
                    id=run_id,
                    tenant_id=user_id,
                    gmail_connection_id=connection_id,
                    status="SUCCESS",
                    started_at=datetime.now(timezone.utc),
                    emails_processed=4,
                    new_codes=1,
                )
            )
            db.add(
                ExtractedError(
                    run_id=run_id,
                    tenant_id=user_id,
                    gmail_connection_id=connection_id,
                    code=code,
                    raw_code=code,
                )
            )
            db.add(
                GmailRegistryEntry(
                    connection_id=connection_id,
                    code=code,
                )
            )
        db.commit()

    monkeypatch.setattr(api_routes, "SessionLocal", database)
    monkeypatch.setattr(connection_routes, "SessionLocal", database)
    monkeypatch.setattr(gmail_oauth, "SessionLocal", database)
    app = FastAPI()
    app.include_router(api_routes.router)
    app.include_router(connection_routes.router)

    @app.middleware("http")
    async def set_test_user(request, call_next):
        request.scope["session"] = {
            "user_id": request.headers.get("x-test-user"),
            "csrf_token": "test-csrf",
        }
        return await call_next(request)

    with TestClient(app) as client:
        headers = {"X-Test-User": "google-user-a"}
        runs = client.get("/api/runs", headers=headers).json()
        connections = client.get("/api/gmail-connections", headers=headers).json()
        registry = client.get("/api/registry", headers=headers).json()

    assert [run["id"] for run in runs] == ["run-a"]
    assert [item["email"] for item in connections] == ["a@example.test"]
    assert [item["code"] for item in registry] == ["ERR-1001"]
    assert "cipher-google-user-a" not in json.dumps(connections)


def test_successful_gmail_callback_saves_encrypted_connection(
    database, monkeypatch
):
    state = "callback-state"
    token_json = json.dumps(
        {
            "token": "oauth-access-token",
            "refresh_token": "oauth-refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        }
    )
    settings = Settings(
        _env_file=None,
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost/auth/gmail/callback",
        google_login_redirect_uri="http://localhost/auth/google/callback",
        session_secret_key="a-stable-test-session-secret-value",
        token_encryption_key=Fernet.generate_key().decode("ascii"),
    )
    with database() as db:
        db.add(AppUser(id="google-user-a", email="owner@example.test"))
        db.commit()
        gmail_oauth.save_oauth_state(
            db,
            state=state,
            browser_id="test-browser",
            purpose="connect",
            user_id="google-user-a",
        )

    class FakeCredentials:
        @staticmethod
        def to_json():
            return token_json

    class FakeFlow:
        credentials = FakeCredentials()

        @staticmethod
        def fetch_token(*, code):
            assert code == "oauth-code"

    class FakeProfileRequest:
        @staticmethod
        def execute():
            return {"emailAddress": "mailbox@example.test"}

    class FakeUsers:
        @staticmethod
        def getProfile(*, userId):
            assert userId == "me"
            return FakeProfileRequest()

    class FakeGmailService:
        @staticmethod
        def users():
            return FakeUsers()

    monkeypatch.setattr(auth_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(auth_routes, "SessionLocal", database)
    monkeypatch.setattr(gmail_oauth, "SessionLocal", database)
    monkeypatch.setattr(auth_routes, "create_flow", lambda *_args, **_kwargs: FakeFlow())
    monkeypatch.setattr(auth_routes, "build", lambda *_args, **_kwargs: FakeGmailService())
    app = FastAPI()
    app.include_router(auth_routes.router)

    @app.middleware("http")
    async def set_test_session(request, call_next):
        request.scope["session"] = {
            "user_id": "google-user-a",
            "browser_id": "test-browser",
            "csrf_token": "test-csrf",
        }
        return await call_next(request)

    with TestClient(app) as client:
        response = client.get(
            "/auth/gmail/callback",
            params={"state": state, "code": "oauth-code"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "gmail=connected" in response.headers["location"]
    with database() as db:
        connection = db.scalar(select(GmailConnection))
        assert connection is not None
        assert connection.user_id == "google-user-a"
        assert connection.email == "mailbox@example.test"
        assert token_json not in connection.encrypted_credentials
        assert decrypt_credentials(settings, connection.encrypted_credentials) == token_json


def test_invalid_gmail_callback_state_does_not_create_connection(database, monkeypatch):
    settings = Settings(
        _env_file=None,
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        google_redirect_uri="http://localhost/auth/gmail/callback",
        google_login_redirect_uri="http://localhost/auth/google/callback",
        session_secret_key="a-stable-test-session-secret-value",
        token_encryption_key=Fernet.generate_key().decode("ascii"),
    )
    with database() as db:
        db.add(AppUser(id="google-user-a", email="owner@example.test"))
        db.commit()
    monkeypatch.setattr(auth_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(auth_routes, "SessionLocal", database)
    monkeypatch.setattr(gmail_oauth, "SessionLocal", database)
    app = FastAPI()
    app.include_router(auth_routes.router)

    @app.middleware("http")
    async def set_test_session(request, call_next):
        request.scope["session"] = {
            "user_id": "google-user-a",
            "browser_id": "test-browser",
        }
        return await call_next(request)

    with TestClient(app) as client:
        response = client.get(
            "/auth/gmail/callback",
            params={"state": "unknown", "code": "oauth-code"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "gmail=failed" in response.headers["location"]
    with database() as db:
        assert db.scalar(select(GmailConnection.id)) is None


def test_scheduler_continues_when_one_gmail_connection_fails(database, monkeypatch):
    with database() as db:
        db.add_all(
            [
                AppUser(id="user-a", email="a@example.test"),
                AppUser(id="user-b", email="b@example.test"),
            ]
        )
        db.flush()
        db.add_all(
            [
                GmailConnection(
                    id="connection-a",
                    user_id="user-a",
                    email="a@example.test",
                    encrypted_credentials="encrypted-a",
                ),
                GmailConnection(
                    id="connection-b",
                    user_id="user-b",
                    email="b@example.test",
                    encrypted_credentials="encrypted-b",
                ),
            ]
        )
        db.commit()

    completed = []

    class FakeService:
        def __init__(self, email):
            self.email = email

        async def run_async(self, _run_id):
            if self.email == "a@example.test":
                raise RuntimeError("sensitive failure")
            completed.append(self.email)

    monkeypatch.setattr(scheduler_module, "SessionLocal", database)
    monkeypatch.setattr(
        "app.gmail_connections.create_account_service",
        lambda connection, _settings: FakeService(connection.email),
    )

    handled_connections = asyncio.run(
        scheduler_module.run_connected_gmail_accounts(
            Settings(_env_file=None, max_email_workers=1)
        )
    )

    assert handled_connections
    assert completed == ["b@example.test"]
    with database() as db:
        failed = db.get(GmailConnection, "connection-a")
        succeeded = db.get(GmailConnection, "connection-b")
        assert failed is not None and failed.status == "OAUTH_ERROR"
        assert succeeded is not None and succeeded.status == "CONNECTED"
