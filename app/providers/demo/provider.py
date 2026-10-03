from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import Settings, get_settings
from app.logging.logger import get_logger
from app.models.email import EmailAttachment, EmailMessage
from app.providers.base import EmailProvider

logger = get_logger("demo_provider")


class DemoEmailProvider(EmailProvider):
    """
    In-memory / Demo Email Provider for local demonstration and automated testing.
    Can simulate both successful email delivery and transient delivery failures.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._authenticated = True
        self.should_fail_send = False
        self.sent_alerts: list[dict] = []
        self._inbox: list[EmailMessage] = []
        self._attachment_payloads: dict[str, bytes] = {}
        self._init_demo_inbox()

    @property
    def provider_name(self) -> str:
        return "demo"

    def authenticate(self) -> bool:
        self._authenticated = True
        return True

    def is_authenticated(self) -> bool:
        return self._authenticated

    def _init_demo_inbox(self):
        """Seed demo inbox with sample error emails."""
        self._inbox.clear()
        self._attachment_payloads.clear()

        # Email 1: Production Database Timeout with production.log attachment
        log_content = (
            "2026-10-03 10:14:02 [ERROR] ERR-5021: Database connection timeout to primary cluster db-01\n"
            "2026-10-03 10:14:05 [WARN] Retrying connection attempt 1/3...\n"
            "2026-10-03 10:14:10 [ERROR] ERR-7788: Payment gateway timeout while processing transaction TX-9921\n"
            "2026-10-03 10:14:12 [FATAL] Transaction rolled back due to gateway error.\n"
        ).encode("utf-8")
        self._attachment_payloads["att_log_001"] = log_content

        msg1 = EmailMessage(
            message_id="demo_msg_001",
            thread_id="thread_prod_001",
            sender="alerts@monitoring.rsr.internal",
            recipients=["ops-team@rsr.internal"],
            subject="[Alert] Production System Incident - DB & Payment Gateway",
            timestamp=datetime.now(timezone.utc),
            body_text=(
                "Alert Sentinel System Notice:\n"
                "Multiple errors detected in production environment.\n"
                "Please review attached production.log immediately.\n"
                "Observed: ERR-5021 database timeout and ERR-7788 payment timeout."
            ),
            body_html="<p>Alert Sentinel System Notice: Production errors detected.</p>",
            has_attachments=True,
            attachments=[
                EmailAttachment(
                    attachment_id="att_log_001",
                    filename="production.log",
                    mime_type="text/plain",
                    size=len(log_content),
                )
            ],
            provider="demo",
        )

        self._inbox.append(msg1)

    def add_custom_message(self, message: EmailMessage, attachment_data: Optional[dict[str, bytes]] = None):
        """Helper to inject specific email scenarios during tests."""
        self._inbox.append(message)
        if attachment_data:
            self._attachment_payloads.update(attachment_data)

    def list_messages(
        self,
        query: Optional[str] = None,
        max_results: int = 25,
        since_timestamp: Optional[str] = None,
    ) -> list[EmailMessage]:
        return list(self._inbox[:max_results])

    def get_message(self, message_id: str) -> Optional[EmailMessage]:
        for msg in self._inbox:
            if msg.message_id == message_id:
                return msg
        return None

    def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        target_path: Path,
    ) -> Path:
        data = self._attachment_payloads.get(attachment_id)
        if data is None:
            data = f"Mock file content for attachment {attachment_id}".encode("utf-8")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(data)
        return target_path

    def send_alert(
        self,
        recipients: list[str],
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
        attachments: Optional[list[Path]] = None,
    ) -> bool:
        if self.should_fail_send:
            logger.warning("Simulated notification failure in DemoEmailProvider (should_fail_send=True)")
            return False

        record = {
            "recipients": recipients,
            "subject": subject,
            "body_html": body_html,
            "body_text": body_text,
            "attachments": [str(p) for p in (attachments or [])],
            "sent_at": datetime.now(timezone.utc),
        }
        self.sent_alerts.append(record)
        logger.info(f"Demo alert simulated successfully to {recipients}: '{subject}'")
        return True
