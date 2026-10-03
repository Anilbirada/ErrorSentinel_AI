"""Provider-independent data models."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def max_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.get(a, 0) >= SEVERITY_ORDER.get(b, 0) else b


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@dataclass
class EmailMessage:
    message_id: str
    sender: str
    subject: str
    timestamp: datetime
    body_text: str = ""
    body_html: str = ""
    thread_id: str = ""
    recipients: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    has_attachments: bool = False
    provider: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AttachmentMeta:
    attachment_id: str
    message_id: str
    filename: str
    mime_type: str = "application/octet-stream"
    size: int = 0


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str = ""
    error: str = ""


@dataclass
class ExtractedDocument:
    filename: str
    mime_type: str
    source_message_id: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    page_count: int | None = None
    sheet_count: int | None = None
    extraction_status: str = "PENDING"   # SUCCESS | FAILED | UNSUPPORTED | SKIPPED_TOO_LARGE
    error_message: str = ""


@dataclass
class RawFinding:
    raw_code: str
    canonical: str           # pre-normalization form, e.g. "ERR-5021"
    message: str
    context: str
    severity: str = "MEDIUM"
    confidence: float | None = None
    rule: str = ""


@dataclass
class ErrorRecord:
    raw_code: str
    normalized_code: str
    message: str
    context: str
    severity: str
    source_message_id: str
    source_email: str
    attachment_name: str
    source_type: str                      # email_body | attachment | pending
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int = 1
    ai_confidence: float | None = None
    run_id: str = ""
    sources: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["first_seen_at"] = iso(self.first_seen_at)
        d["last_seen_at"] = iso(self.last_seen_at)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ErrorRecord":
        d = dict(d)
        d["first_seen_at"] = datetime.fromisoformat(d["first_seen_at"])
        d["last_seen_at"] = datetime.fromisoformat(d["last_seen_at"])
        return cls(**d)


@dataclass
class RunResult:
    run_id: str
    status: str                            # completed | notification_failed | failed | already_running
    emails_scanned: int = 0
    emails_processed: int = 0
    attachments_processed: int = 0
    errors_extracted: int = 0
    new_codes: list[str] = field(default_factory=list)
    existing_codes: list[str] = field(default_factory=list)
    notification_status: str = "NOT_NEEDED"   # NOT_NEEDED | SENT | FAILED
    registry_status: str = "UNCHANGED"        # UNCHANGED | COMMITTED
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    report_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
