from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from app.models.email import EmailAttachment, EmailMessage


class EmailProvider(ABC):
    """
    Abstract Email Provider interface.
    Both GmailProvider and MicrosoftGraphProvider (as well as Demo/Mock providers)
    implement this contract so ErrorSentinel business logic remains provider-independent.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Returns provider identifier name (e.g. 'gmail', 'microsoft_graph', 'demo')."""
        pass

    @abstractmethod
    def authenticate(self) -> bool:
        """Authenticate with provider and verify access credentials."""
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Return True if provider is currently authenticated and ready."""
        pass

    @abstractmethod
    def list_messages(
        self,
        query: Optional[str] = None,
        max_results: int = 25,
        since_timestamp: Optional[str] = None,
    ) -> list[EmailMessage]:
        """List messages matching filter or query."""
        pass

    @abstractmethod
    def get_message(self, message_id: str) -> Optional[EmailMessage]:
        """Fetch complete email message details, body, and attachment metadata."""
        pass

    @abstractmethod
    def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        target_path: Path,
    ) -> Path:
        """Download an attachment and save to local path."""
        pass

    @abstractmethod
    def send_alert(
        self,
        recipients: list[str],
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
        attachments: Optional[list[Path]] = None,
    ) -> bool:
        """
        Send an email alert.
        Must return True ONLY upon verified successful submission/delivery.
        """
        pass
