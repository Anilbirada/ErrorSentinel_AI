"""Environment-driven configuration with validation. Secrets are never logged."""
from __future__ import annotations

import os
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path

KNOWN_EMAIL_PROVIDERS = {"gmail", "microsoft_graph", "memory"}
KNOWN_LLM_PROVIDERS = {"", "none", "mock", "anthropic"}


def load_env_file(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    email_provider: str = "gmail"
    gmail_user: str = ""
    gmail_credentials_file: str = ""
    gmail_token_file: str = ""
    llm_provider: str = ""
    llm_api_key: str = field(default="", repr=False)
    llm_model: str = ""
    llm_max_chars: int = 6000
    llm_retries: int = 2
    llm_timeout_s: float = 30.0
    monitor_interval_minutes: int = 30
    max_email_workers: int = 5
    max_attachment_workers: int = 5
    max_llm_concurrency: int = 3
    max_attachment_size_mb: int = 25
    database_url: str = "sqlite:///data/app.db"
    report_output_dir: str = "reports"
    log_dir: str = "logs"
    registry_file: str = "data/existing_error_codes.txt"
    patterns_file: str = ""
    alert_recipients: list[str] = field(default_factory=list)
    notify_retries: int = 3
    notify_backoff_s: float = 1.0
    scan_overlap_minutes: int = 10
    parse_errors: list[str] = field(default_factory=list, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        kwargs: dict = {}
        errors: list[str] = []
        for f in fields(cls):
            if f.name == "parse_errors":
                continue
            raw = os.environ.get(f.name.upper(), "").strip()
            if not raw:
                continue
            default = f.default if f.default is not MISSING else f.default_factory()  # type: ignore[misc]
            try:
                if isinstance(default, list):
                    kwargs[f.name] = [x.strip() for x in raw.split(",") if x.strip()]
                elif isinstance(default, bool):
                    kwargs[f.name] = raw.lower() in {"1", "true", "yes"}
                elif isinstance(default, int):
                    kwargs[f.name] = int(raw)
                elif isinstance(default, float):
                    kwargs[f.name] = float(raw)
                else:
                    kwargs[f.name] = raw
            except ValueError:
                errors.append(f"{f.name.upper()} has an invalid value")
        return cls(**kwargs, parse_errors=errors)

    @property
    def sqlite_path(self) -> str:
        prefix = "sqlite:///"
        return self.database_url[len(prefix):] if self.database_url.startswith(prefix) else ""

    @property
    def max_attachment_bytes(self) -> int:
        return self.max_attachment_size_mb * 1024 * 1024

    def validate(self) -> list[str]:
        problems = list(self.parse_errors)
        if self.email_provider not in KNOWN_EMAIL_PROVIDERS:
            problems.append(f"EMAIL_PROVIDER must be one of {sorted(KNOWN_EMAIL_PROVIDERS)}")
        if self.email_provider == "gmail":
            for name in ("gmail_user", "gmail_credentials_file", "gmail_token_file"):
                if not getattr(self, name):
                    problems.append(f"{name.upper()} is required when EMAIL_PROVIDER=gmail")
        if self.llm_provider not in KNOWN_LLM_PROVIDERS:
            problems.append(f"LLM_PROVIDER must be one of {sorted(KNOWN_LLM_PROVIDERS - {''})} or empty")
        if self.llm_provider == "anthropic" and not (self.llm_api_key and self.llm_model):
            problems.append("LLM_API_KEY and LLM_MODEL are required when LLM_PROVIDER=anthropic")
        for name in ("monitor_interval_minutes", "max_email_workers", "max_attachment_workers",
                     "max_llm_concurrency", "max_attachment_size_mb", "app_port"):
            if getattr(self, name) <= 0:
                problems.append(f"{name.upper()} must be greater than 0")
        if not self.sqlite_path:
            problems.append("DATABASE_URL must start with sqlite:/// (PostgreSQL support is planned)")
        if not self.alert_recipients:
            problems.append("ALERT_RECIPIENTS must list at least one address")
        return problems

    def redacted(self) -> dict:
        data = asdict(self)
        data["llm_api_key"] = "(set)" if self.llm_api_key else "(not set)"
        data.pop("parse_errors", None)
        return data
