from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models import AlertDelivery
from app.logging.logger import get_logger
from app.models.extraction import ErrorRecord
from app.models.jobs import MonitoringRunModel
from app.providers.base import EmailProvider
from app.registry.repository import RegistryRepository

logger = get_logger("notification_service")


class NotificationService:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    def dispatch_alert_and_commit(
        self,
        provider: EmailProvider,
        db_session: Session,
        run: MonitoringRunModel,
        new_errors: list[ErrorRecord],
        html_report_path: Optional[Path] = None,
        recipients_override: Optional[list[str]] = None,
    ) -> tuple[bool, str]:
        """
        MANDATORY TRANSACTION WORKFLOW:
        1. Build email alert
        2. Attempt delivery via configured EmailProvider
        3. IF SUCCESS:
           - Update SQLite Registry inside database transaction
           - Synchronize text registry
           - Return (True, "Delivered and registry committed")
        4. IF FAILURE:
           - DO NOT UPDATE REGISTRY
           - Record delivery failure audit log
           - Return (False, "Delivery failed; registry unchanged")
        """
        if not new_errors:
            logger.info(f"No new errors in run {run.run_id}; skipping notification.")
            return True, "No new errors; alert skipped"

        recipients = recipients_override or self.settings.recipients
        if not recipients:
            # Fallback for demo or test mailbox
            recipients = [self.settings.monitor_mailbox or "ops@rsr.internal"]

        count = len(new_errors)
        codes_preview = ", ".join(e.normalized_code for e in new_errors[:4])
        if count > 4:
            codes_preview += f" (+{count - 4} more)"

        subject = f"[RSR ErrorSentinel AI] {count} New Error(s) Detected — {codes_preview}"

        # Read HTML report content or build alert body
        body_html = ""
        if html_report_path and html_report_path.exists():
            with open(html_report_path, "r", encoding="utf-8") as f:
                body_html = f.read()
        else:
            body_html = f"<h2>RSR ErrorSentinel AI Alert</h2><p>{count} new error(s) detected in run {run.run_id}: {codes_preview}</p>"

        body_text = (
            f"RSR ErrorSentinel AI Alert\n"
            f"Run ID: {run.run_id}\n"
            f"New Errors Detected: {count} ({codes_preview})\n"
            f"Please inspect attached report for details."
        )

        attachments = [html_report_path] if (html_report_path and html_report_path.exists()) else []

        # Attempt delivery
        delivery_success = False
        error_msg = None
        try:
            delivery_success = provider.send_alert(
                recipients=recipients,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                attachments=attachments if self.settings.enable_email_attachments else None,
            )
        except Exception as e:
            delivery_success = False
            error_msg = str(e)
            logger.error(f"Exception raised while sending alert: {str(e)}", exc_info=True)

        # Audit delivery attempt in database
        audit_record = AlertDelivery(
            run_id=run.run_id,
            recipient=", ".join(recipients),
            subject=subject,
            status="SUCCESS" if delivery_success else "FAILED",
            sent_at=datetime.now(timezone.utc) if delivery_success else None,
            error=error_msg,
            report_path=str(html_report_path or ""),
        )
        db_session.add(audit_record)
        db_session.commit()

        # MANDATORY TRANSACTION ENFORCEMENT
        if delivery_success:
            logger.info(f"Alert delivered successfully for run {run.run_id}. Proceeding to registry commit.")
            registry_repo = RegistryRepository(db_session)
            committed = registry_repo.commit_new_errors(
                errors=new_errors,
                run_id=run.run_id,
                txt_path=self.settings.registry_file,
            )
            run.notification_status = "SENT"
            run.registry_status = "COMMITTED"
            return True, f"Alert delivered and {len(committed)} new error(s) committed to registry"
        else:
            logger.warning(
                f"Alert delivery FAILED for run {run.run_id}. "
                "TRANSACTION RULE ENFORCED: Master registry remains strictly UNCHANGED."
            )
            run.notification_status = "FAILED"
            run.registry_status = "UNCHANGED"
            return False, f"Alert delivery failed ({error_msg or 'provider rejected'}); registry unchanged."
