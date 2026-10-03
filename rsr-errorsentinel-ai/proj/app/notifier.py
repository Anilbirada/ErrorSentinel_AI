"""Alert delivery with retries. Success means the provider ACCEPTED the message."""
from __future__ import annotations

import logging
import time

from .database import Database
from .models import iso, utcnow
from .providers.base import EmailProvider

log = logging.getLogger("sentinel.notify")


class Notifier:
    def __init__(self, provider: EmailProvider, db: Database, recipients: list[str],
                 retries: int = 3, backoff_s: float = 1.0) -> None:
        self.provider, self.db, self.recipients = provider, db, recipients
        self.retries, self.backoff_s = retries, backoff_s

    def send_alert(self, run_id: str, new_count: int, html_body: str, text_body: str,
                   attachments: list[tuple[str, str, bytes]]) -> bool:
        subject = f"[RSR ErrorSentinel AI] {new_count} New Error{'s' if new_count != 1 else ''} Detected"
        for attempt in range(1, self.retries + 1):
            try:
                result = self.provider.send_message(self.recipients, subject, html_body, text_body, attachments)
                ok, pid, err = result.ok, result.provider_message_id, result.error
            except Exception as exc:
                ok, pid, err = False, "", type(exc).__name__
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO notification_attempts(run_id,attempt,status,provider_message_id,error_message,created_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (run_id, attempt, "SENT" if ok else "FAILED", pid, err[:200], iso(utcnow())))
            if ok:
                log.info("alert sent run=%s attempt=%d", run_id, attempt)
                return True
            log.warning("alert failed run=%s attempt=%d: %s", run_id, attempt, err)
            if attempt < self.retries:
                time.sleep(self.backoff_s * (2 ** (attempt - 1)))
        return False
