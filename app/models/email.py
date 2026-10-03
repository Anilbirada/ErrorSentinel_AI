from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class EmailAttachment:
    attachment_id: str
    filename: str
    mime_type: str
    size: int
    data: Optional[bytes] = None
    local_path: Optional[str] = None
    hash: Optional[str] = None


@dataclass
class EmailMessage:
    message_id: str
    thread_id: str = ""
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    subject: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    body_text: str = ""
    body_html: str = ""
    labels: list[str] = field(default_factory=list)
    has_attachments: bool = False
    attachments: list[EmailAttachment] = field(default_factory=list)
    provider: str = "gmail"
    raw_metadata: dict[str, Any] = field(default_factory=dict)
