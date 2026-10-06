from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Application settings
    app_name: str = "RSR ErrorSentinel AI"
    app_title: str = "RSR ErrorSentinel AI — Email Error Intelligence & Monitoring Agent"
    app_tagline: str = "Detect. Understand. Verify. Alert."
    app_env: Literal["development", "test", "production", "demo"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    host: str = "0.0.0.0"
    port: int = 8000

    # Email Provider configuration: "gmail", "microsoft_graph", "demo", "mock"
    email_provider: Literal["gmail", "microsoft_graph", "demo", "mock"] = "gmail"

    # Gmail Configuration (OAuth & API)
    gmail_user: str = "me"
    gmail_credentials_file: str = "credentials.json"
    gmail_token_file: str = "token.json"
    gmail_scopes: str = "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    google_login_redirect_uri: str = ""
    token_encryption_key: str = ""
    session_secret_key: str = ""
    gmail_max_connections: int = Field(default=10, ge=1, le=100)

    # Microsoft Graph Configuration (Future / Enterprise)
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    monitor_mailbox: str = ""
    alert_from_mailbox: str = ""
    alert_recipients: str = ""

    # AI / LLM Configuration
    llm_provider: Literal["mock", "openai", "gemini", "anthropic", "ollama", "none"] = "mock"
    ai_provider: str = "none"  # compatibility alias
    llm_api_key: str = ""
    ai_api_key: str = ""  # compatibility alias
    llm_model: str = "gpt-4o-mini"
    ai_model: str = ""  # compatibility alias
    max_llm_concurrency: int = Field(default=3, ge=1, le=20)
    max_llm_input_chars: int = Field(default=50000, ge=1000)

    # Concurrency & Processing Limits
    max_email_workers: int = Field(default=5, ge=1, le=50)
    max_attachment_workers: int = Field(default=5, ge=1, le=50)
    max_attachment_size_mb: int = Field(default=25, ge=1, le=100)
    monitor_interval_minutes: int = Field(default=30, ge=1, le=1440)
    schedule_minutes: int = Field(default=30, ge=1, le=1440)  # compatibility alias

    # Database & Storage paths
    database_url: str = "sqlite:///./data/app.db"
    registry_file: Path = ROOT / "data" / "existing_error_codes.txt"
    reports_dir: Path = ROOT / "reports"
    downloads_dir: Path = ROOT / "downloads"
    logs_dir: Path = ROOT / "logs"

    # Security & Logging
    log_level: str = "INFO"
    api_key: str = ""
    enable_dashboard: bool = True
    enable_email_attachments: bool = False
    cors_origins: str = "http://localhost:5173,http://localhost:8000,http://127.0.0.1:8000"

    @property
    def recipients(self) -> list[str]:
        if not self.alert_recipients:
            return []
        return [x.strip() for x in self.alert_recipients.split(",") if x.strip()]

    @property
    def active_llm_provider(self) -> str:
        if self.llm_provider and self.llm_provider != "none":
            return self.llm_provider
        if self.ai_provider and self.ai_provider != "none":
            return self.ai_provider
        return "mock"

    @property
    def active_llm_key(self) -> str:
        return self.llm_api_key or self.ai_api_key or ""

    @property
    def active_llm_model(self) -> str:
        return self.llm_model or self.ai_model or "gpt-4o-mini"

    @property
    def missing_gmail_settings(self) -> list[str]:
        missing = []
        cred_path = Path(self.gmail_credentials_file)
        if not cred_path.is_absolute():
            cred_path = ROOT / cred_path
        if not cred_path.exists():
            missing.append(f"GMAIL_CREDENTIALS_FILE ({self.gmail_credentials_file} not found)")
        return missing

    @property
    def missing_graph_settings(self) -> list[str]:
        required = (
            ("MS_TENANT_ID", self.ms_tenant_id),
            ("MS_CLIENT_ID", self.ms_client_id),
            ("MS_CLIENT_SECRET", self.ms_client_secret),
            ("MONITOR_MAILBOX", self.monitor_mailbox),
            ("ALERT_FROM_MAILBOX", self.alert_from_mailbox),
            ("ALERT_RECIPIENTS", ", ".join(self.recipients)),
        )
        return [name for name, value in required if not value.strip()]

    @property
    def graph_ready(self) -> bool:
        return not self.missing_graph_settings

    @property
    def gmail_ready(self) -> bool:
        return not self.missing_gmail_settings

    @property
    def google_oauth_ready(self) -> bool:
        required_settings_present = (
            self.google_client_id.strip()
            and self.google_client_secret.strip()
            and self.google_redirect_uri.strip()
            and self.google_login_redirect_uri.strip()
            and len(self.session_secret_key.encode("utf-8")) >= 32
        )
        if not required_settings_present or not self.token_encryption_key.strip():
            return False
        try:
            Fernet(self.token_encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            return False
        return True

    @field_validator("cors_origins")
    @classmethod
    def strip_origins(cls, value: str) -> str:
        return value.strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
