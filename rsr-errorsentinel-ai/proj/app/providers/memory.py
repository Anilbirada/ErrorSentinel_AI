"""In-memory provider used by demo mode and tests. Not a fake integration: it is the
reference implementation of the EmailProvider contract for offline use."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterator

from ..models import AttachmentMeta, EmailMessage, SendResult
from .base import EmailProvider


class MemoryProvider(EmailProvider):
    name = "memory"

    def __init__(self) -> None:
        self._messages: dict[str, EmailMessage] = {}
        self._attachments: dict[str, dict[str, tuple[AttachmentMeta, bytes]]] = {}
        self.outbox: list[dict] = []
        self.fail_sends = False
        self.fail_listing = False
        self.on_list: Callable[[], None] | None = None   # test hook (e.g. block to test overlap)

    def add_message(self, msg: EmailMessage, attachments: list[tuple[str, str, bytes]] | None = None) -> None:
        msg.provider = self.name
        atts: dict[str, tuple[AttachmentMeta, bytes]] = {}
        for i, (fname, mime, data) in enumerate(attachments or []):
            aid = f"{msg.message_id}-att{i}"
            atts[aid] = (AttachmentMeta(aid, msg.message_id, fname, mime, len(data)), data)
        msg.has_attachments = bool(atts)
        self._messages[msg.message_id] = msg
        self._attachments[msg.message_id] = atts

    def authenticate(self) -> None:
        return None

    def list_messages(self, after: datetime | None = None) -> Iterator[EmailMessage]:
        if self.on_list:
            self.on_list()
        if self.fail_listing:
            raise ConnectionError("provider unavailable")
        for msg in sorted(self._messages.values(), key=lambda m: m.timestamp):
            if after is None or msg.timestamp > after:
                yield msg

    def get_message(self, message_id: str) -> EmailMessage:
        return self._messages[message_id]

    def list_attachments(self, message_id: str) -> list[AttachmentMeta]:
        return [meta for meta, _ in self._attachments.get(message_id, {}).values()]

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        return self._attachments[message_id][attachment_id][1]

    def send_message(self, to, subject, body_html, body_text, attachments=None) -> SendResult:
        if self.fail_sends:
            return SendResult(False, error="simulated delivery failure")
        self.outbox.append({"to": to, "subject": subject, "html": body_html, "text": body_text,
                            "attachments": [a[0] for a in attachments or []]})
        return SendResult(True, provider_message_id=f"mem-{len(self.outbox)}")
