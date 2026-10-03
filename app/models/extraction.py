from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class ExtractedDocument:
    filename: str
    mime_type: str
    source_message_id: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    page_count: int = 1
    sheet_count: int = 1
    extraction_status: str = "SUCCESS"
    error_message: Optional[str] = None
    size: int = 0
    hash: str = ""
    local_path: Optional[str] = None


@dataclass
class ErrorRecord:
    id: Optional[int] = None
    raw_code: str = ""
    normalized_code: str = ""
    message: str = ""
    context: str = ""
    severity: SeverityLevel = SeverityLevel.MEDIUM
    source_message_id: str = ""
    source_email: str = ""
    sender: str = ""
    attachment_name: str = ""
    source_type: str = "email_body"
    occurrence_count: int = 1
    first_seen_at: datetime = field(default_factory=now_utc)
    last_seen_at: datetime = field(default_factory=now_utc)
    ai_confidence: float = 1.0
    run_id: str = ""
    is_new: bool = False
    ai_interpretation: Optional[str] = None
