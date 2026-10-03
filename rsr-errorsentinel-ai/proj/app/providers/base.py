"""Provider contract. Core logic depends ONLY on this interface (Gmail / Graph plug in here)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator

from ..models import AttachmentMeta, EmailMessage, SendResult


class EmailProvider(ABC):
    name = "base"

    @abstractmethod
    def authenticate(self) -> None: ...

    @abstractmethod
    def list_messages(self, after: datetime | None = None) -> Iterator[EmailMessage]:
        """Yield messages newer than `after`, handling pagination internally."""

    @abstractmethod
    def get_message(self, message_id: str) -> EmailMessage: ...

    @abstractmethod
    def list_attachments(self, message_id: str) -> list[AttachmentMeta]: ...

    @abstractmethod
    def download_attachment(self, message_id: str, attachment_id: str) -> bytes: ...

    @abstractmethod
    def send_message(self, to: list[str], subject: str, body_html: str, body_text: str,
                     attachments: list[tuple[str, str, bytes]] | None = None) -> SendResult:
        """Return ok=True only when the provider accepted the message for delivery."""
