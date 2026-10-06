from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from google.auth.credentials import Credentials as BaseCredentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from sqlalchemy import select

from app.auth.gmail_oauth import decrypt_credentials, encrypt_credentials
from app.config import Settings, get_settings
from app.database.models import GmailConnection
from app.database.session import SessionLocal
from app.jobs.manager import get_job_manager
from app.models.jobs import JobStatus
from app.providers.gmail.provider import GmailProvider
from app.services import MonitoringService


class PersistingCredentials(BaseCredentials):
    def __init__(self, credentials: Credentials, persist) -> None:
        super().__init__(token=credentials.token)
        self._credentials = credentials
        self._persist = persist

    def __getattr__(self, name: str):
        return getattr(self._credentials, name)

    def apply(self, headers, token=None):
        self._credentials.apply(headers, token=token)
        self.token = self._credentials.token

    def refresh(self, request: Request) -> None:
        self._credentials.refresh(request)
        self.token = self._credentials.token
        self._persist(self._credentials.to_json())


def account_settings(settings: Settings, connection_id: str, email: str) -> Settings:
    account_root = settings.reports_dir / "gmail_accounts" / connection_id
    return settings.model_copy(
        update={
            "registry_file": account_root / "existing_error_codes.txt",
            "downloads_dir": account_root / "downloads",
            "reports_dir": account_root / "reports",
            "gmail_user": email,
        }
    )


def create_account_service(
    connection: GmailConnection,
    settings: Optional[Settings] = None,
) -> MonitoringService:
    config = settings or get_settings()
    scoped_settings = account_settings(config, connection.id, connection.email)
    credential_data = json.loads(
        decrypt_credentials(config, connection.encrypted_credentials)
    )
    credentials = Credentials.from_authorized_user_info(
        credential_data,
        scopes=[scope.strip() for scope in config.gmail_scopes.split(",") if scope.strip()],
    )

    def save_refreshed_credentials(credentials_json: str) -> None:
        encrypted = encrypt_credentials(config, credentials_json)
        with SessionLocal() as db:
            current = db.scalar(
                select(GmailConnection).where(
                    GmailConnection.id == connection.id,
                    GmailConnection.user_id == connection.user_id,
                )
            )
            if current is not None and current.status != "DISCONNECTED":
                current.encrypted_credentials = encrypted
                current.updated_at = datetime.now(timezone.utc)
                db.commit()

    persisting_credentials = PersistingCredentials(
        credentials,
        save_refreshed_credentials,
    )
    provider = GmailProvider(
        scoped_settings,
        credentials=persisting_credentials,
        strict_auth=True,
    )
    return MonitoringService(
        scoped_settings,
        provider=provider,
        tenant_id=connection.user_id,
        gmail_connection_id=connection.id,
        alert_recipient=connection.email,
    )


def execute_tracked_monitoring(
    service: MonitoringService,
    run_id: str,
    job_id: str,
) -> None:
    try:
        result = service.execute_monitoring_cycle(run_id)
        status = JobStatus.SUCCESS if result.status == JobStatus.SUCCESS else JobStatus.FAILED
        get_job_manager().update_job_status(
            job_id,
            status,
            error_message=result.error_message,
        )
    except Exception:
        get_job_manager().update_job_status(
            job_id,
            JobStatus.FAILED,
            error_message="Monitoring temporarily failed. The system will retry.",
        )
