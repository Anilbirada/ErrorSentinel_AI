from __future__ import annotations

import asyncio
import base64
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.provider import get_llm_provider
from app.attachments.downloader import AttachmentDownloader, save_attachment
from app.config import Settings, get_settings
from app.database.models import (
    AlertDelivery,
    AttachmentRecord,
    EmailRecord,
    ErrorRegistryEntry,
    ExtractedError,
    MonitoringRun,
)
from app.database.session import SessionLocal
from app.errors.deduplicator import deduplicate, deduplicate_errors
from app.errors.extractor import ErrorFinding, extract_error_records, extract_errors
from app.errors.normalizer import normalize_code
from app.extraction.dispatcher import extract_document, extract_file
from app.jobs.manager import get_job_manager
from app.logging.logger import get_logger
from app.models.email import EmailMessage
from app.models.extraction import ErrorRecord, SeverityLevel
from app.models.jobs import JobStatus, JobType, MonitoringRunModel, RunMetrics
from app.notifications.notifier import NotificationService
from app.outlook.graph_client import GraphClient
from app.providers.base import EmailProvider
from app.providers.factory import get_email_provider
from app.registry.repository import RegistryRepository
from app.registry.txt_registry import TxtRegistry
from app.reporting.html_report import persist_report, render_report
from app.reporting.report_generator import save_reports
from app.state.state_manager import StateManager

logger = get_logger("monitoring_service")


class RunService:
    """Legacy RunService preserving Graph client retry semantics for tests."""
    _lock = asyncio.Lock()

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _recover_delivered_registry_updates(self, db: Session) -> None:
        """Complete a durable send-success/registry-update after a process crash."""
        registry = RegistryRepository(db)
        delivered = db.scalars(
            select(AlertDelivery).where(AlertDelivery.status == "SUCCESS")
        ).all()
        txt_registry = TxtRegistry(self.settings.registry_file)

        for delivery in delivered:
            codes = set(
                db.scalars(
                    select(ExtractedError.code).where(
                        ExtractedError.run_id == delivery.run_id
                    )
                ).all()
            )
            missing_from_txt = codes - txt_registry.get_all_codes()
            missing_from_database = codes - registry.codes()
            if missing_from_txt:
                txt_registry.add_codes(missing_from_txt)
            if missing_from_database:
                registry.add(missing_from_database, delivery.run_id)
        db.commit()

    @staticmethod
    def _unregistered_findings(db: Session, known_codes: set[str]) -> list[ErrorFinding]:
        """Requeue persisted findings whose alert was not confirmed as delivered."""
        rows = db.scalars(select(ExtractedError)).all()
        findings: list[ErrorFinding] = []
        for row in rows:
            if row.code not in known_codes:
                findings.append(
                    ErrorFinding(
                        code=row.code,
                        message=row.message,
                        context=row.context,
                        severity=row.severity,
                        confidence=float(row.confidence),
                        source=row.source,
                    )
                )
        return findings

    async def run(self) -> str:
        if self.settings.missing_graph_settings:
            raise RuntimeError(
                "Microsoft Graph configuration is incomplete; see /api/preflight"
            )
        if self._lock.locked():
            raise RuntimeError("A monitoring run is already active")

        async with self._lock:
            db: Session = SessionLocal()
            run = MonitoringRun(status="RUNNING")
            db.add(run)
            db.commit()
            db.refresh(run)
            client = GraphClient(self.settings)

            try:
                self._recover_delivered_registry_updates(db)
                txt_registry = TxtRegistry(self.settings.registry_file)
                known_codes = (
                    RegistryRepository(db).codes() | txt_registry.get_all_codes()
                )
                findings = self._unregistered_findings(db, known_codes)
                checkpoint = db.scalar(
                    select(func.max(EmailRecord.received_at)).where(
                        EmailRecord.processing_status == "success"
                    )
                )

                async for message in client.messages_since(
                    checkpoint.isoformat() if checkpoint else None
                ):
                    run.emails_scanned += 1
                    if db.get(EmailRecord, message["id"]):
                        continue

                    sender = (
                        (message.get("from") or {}).get("emailAddress") or {}
                    ).get("address", "")
                    body = (message.get("body") or {}).get("content", "")
                    received = (
                        datetime.fromisoformat(
                            message["receivedDateTime"].replace("Z", "+00:00")
                        )
                        if message.get("receivedDateTime")
                        else None
                    )
                    email = EmailRecord(
                        id=message["id"],
                        internet_message_id=message.get("internetMessageId"),
                        sender=sender,
                        subject=message.get("subject", "") or "",
                        received_at=received,
                        processed_at=datetime.now(timezone.utc),
                        processing_status="success",
                        run_id=run.id,
                    )
                    db.add(email)
                    findings.extend(
                        extract_errors(
                            f"{email.subject}\n{body}", f"email:{email.id}"
                        )
                    )
                    run.emails_processed += 1

                    if (
                        message.get("hasAttachments")
                        and self.settings.enable_email_attachments
                    ):
                        for attachment in await client.attachments(email.id):
                            attachment_id = attachment.get("id", "")
                            record = AttachmentRecord(
                                id=attachment_id
                                or f"{email.id}:{run.attachments_processed}",
                                message_id=email.id,
                                filename=attachment.get("name", "attachment"),
                                mime_type=attachment.get("contentType", ""),
                                size=int(attachment.get("size", 0)),
                                download_status="SKIPPED",
                                extraction_status="SKIPPED",
                            )
                            db.add(record)
                            try:
                                encoded = attachment.get("contentBytes")
                                if not encoded:
                                    raise ValueError(
                                        "Attachment content was not returned by Graph"
                                    )
                                content = base64.b64decode(encoded, validate=True)
                                path = await save_attachment(
                                    content,
                                    record.filename,
                                    self.settings.downloads_dir / run.id,
                                    self.settings.max_attachment_size_mb * 1024 * 1024,
                                )
                                record.download_status = "SUCCESS"
                                result = extract_file(path)
                                record.extraction_status = (
                                    "SUCCESS" if not result.warnings else "PARTIAL"
                                )
                                record.extraction_error = (
                                    "; ".join(result.warnings) or None
                                )
                                findings.extend(
                                    extract_errors(
                                        result.text,
                                        f"attachment:{email.id}/{record.filename}",
                                    )
                                )
                                run.attachments_processed += 1
                            except Exception as exc:
                                record.download_status = "FAILED"
                                record.extraction_status = "FAILED"
                                record.extraction_error = type(exc).__name__
                                run.failures += 1
                                logger.warning(
                                    "Attachment processing failed for message %s",
                                    email.id,
                                )

                groups = deduplicate(findings)
                registry = RegistryRepository(db)
                known_codes = registry.codes() | txt_registry.get_all_codes()
                new_codes = set(groups) - known_codes
                run.new_codes = len(new_codes)
                run.known_codes = len(set(groups) & known_codes)

                for code, group in groups.items():
                    finding = group["finding"]
                    db.add(
                        ExtractedError(
                            run_id=run.id,
                            code=code,
                            message=finding.message,
                            context=finding.context,
                            severity=finding.severity,
                            confidence=str(finding.confidence),
                            source=",".join(group["sources"]),
                        )
                    )

                html = render_report(
                    run.id, self.settings.monitor_mailbox, groups, new_codes
                )
                report_path, _ = persist_report(
                    self.settings.reports_dir,
                    run.id,
                    html,
                    {
                        "run_id": run.id,
                        "new_codes": sorted(new_codes),
                        "groups": {
                            code: {
                                "occurrences": group["occurrences"],
                                "sources": sorted(group["sources"]),
                            }
                            for code, group in groups.items()
                        },
                    },
                )

                if new_codes:
                    delivery = AlertDelivery(
                        run_id=run.id,
                        status="PENDING",
                        report_path=str(report_path),
                    )
                    db.add(delivery)
                    db.commit()
                    try:
                        await client.send_mail(
                            "[RSR ErrorSentinel AI] New Error Codes Detected "
                            f"— {len(new_codes)}",
                            html,
                        )
                    except Exception as exc:
                        delivery.status = "FAILED"
                        delivery.error = type(exc).__name__
                        run.status = "PARTIAL"
                        run.failures += 1
                        logger.error(
                            "Alert delivery failed (%s)", type(exc).__name__
                        )
                    else:
                        delivery.status = "SUCCESS"
                        delivery.sent_at = datetime.now(timezone.utc)
                        db.commit()
                        txt_registry.add_codes(new_codes)
                        registry.add(new_codes, run.id)
                        db.commit()

                if run.status == "RUNNING":
                    run.status = "SUCCESS"
                run.completed_at = datetime.now(timezone.utc)
                db.commit()
                return run.id
            except Exception as exc:
                db.rollback()
                failed_run = db.get(MonitoringRun, run.id)
                if failed_run is not None:
                    failed_run.status = "FAILED"
                    failed_run.failures += 1
                    failed_run.completed_at = datetime.now(timezone.utc)
                    db.commit()
                logger.error("Monitoring run failed (%s)", type(exc).__name__)
                raise
            finally:
                try:
                    await client.aclose()
                finally:
                    db.close()


class MonitoringService:
    """
    Central business engine for RSR ErrorSentinel AI:
    Monitors inbox, extracts text & errors, compares with master registry deterministically,
    generates reports, sends alerts, and enforces atomic registry commits.
    """
    _async_lock = asyncio.Lock()

    def __init__(
        self,
        settings: Optional[Settings] = None,
        provider: Optional[EmailProvider] = None,
        tenant_id: Optional[str] = None,
        gmail_connection_id: Optional[str] = None,
        alert_recipient: Optional[str] = None,
    ):
        self.settings = settings or get_settings()
        self.provider = provider or get_email_provider(settings=self.settings)
        self.tenant_id = tenant_id
        self.gmail_connection_id = gmail_connection_id
        self.job_manager = get_job_manager()
        self.downloader = AttachmentDownloader(self.settings)
        self.notification_service = NotificationService(
            self.settings,
            tenant_id=tenant_id,
            connection_id=gmail_connection_id,
            recipients_override=[alert_recipient] if alert_recipient else None,
        )

    def execute_monitoring_cycle(
        self,
        run_id: Optional[str] = None,
        provider_override: Optional[EmailProvider] = None,
    ) -> MonitoringRunModel:
        """
        Synchronous / Worker entry point for a full monitoring cycle.
        Tracks fine-grained performance timings.
        """
        active_provider = provider_override or self.provider
        run_id = run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:6]}"
        start_total = time.perf_counter()

        metrics = RunMetrics()
        run_model = MonitoringRunModel(
            run_id=run_id,
            status=JobStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            metrics=metrics,
        )

        with SessionLocal() as db:
            db_run = MonitoringRun(
                id=run_id,
                status="RUNNING",
                started_at=run_model.started_at,
                tenant_id=self.tenant_id,
                gmail_connection_id=self.gmail_connection_id,
            )
            db.add(db_run)
            db.commit()

            def ensure_connection_active() -> None:
                if not self.gmail_connection_id:
                    return
                from app.database.models import GmailConnection

                status = db.scalar(
                    select(GmailConnection.status).where(
                        GmailConnection.id == self.gmail_connection_id
                    )
                )
                if status != "CONNECTED":
                    raise RuntimeError("Gmail connection is no longer active")

            state_mgr = StateManager(
                db,
                tenant_id=self.tenant_id,
                connection_id=self.gmail_connection_id,
            )
            registry_repo = RegistryRepository(db, connection_id=self.gmail_connection_id)
            txt_reg = TxtRegistry(self.settings.registry_file)

            try:
                ensure_connection_active()
                # 1. SCAN EMAILS
                logger.info(f"Starting Monitoring Run {run_id} via provider '{active_provider.provider_name}'...")
                job_scan = self.job_manager.create_job(
                    run_id,
                    JobType.EMAIL_SCAN,
                    tenant_id=self.tenant_id,
                    gmail_connection_id=self.gmail_connection_id,
                )
                self.job_manager.update_job_status(job_scan.job_id, JobStatus.RUNNING)

                t0 = time.perf_counter()
                messages: list[EmailMessage] = active_provider.list_messages(max_results=50)
                metrics.gmail_fetch_ms = (time.perf_counter() - t0) * 1000

                run_model.emails_scanned = len(messages)
                self.job_manager.update_job_status(job_scan.job_id, JobStatus.SUCCESS)

                # 2. PROCESS MESSAGES & ATTACHMENTS
                all_raw_errors: list[ErrorRecord] = []
                llm = get_llm_provider(self.settings)

                for msg in messages:
                    ensure_connection_active()
                    if state_mgr.is_message_processed(msg.message_id):
                        logger.debug(f"Skipping already processed message {msg.message_id}")
                        continue

                    run_model.emails_processed += 1
                    t_msg = time.perf_counter()

                    content_text = f"{msg.subject}\n{msg.body_text or ''}"
                    body_errors = extract_error_records(
                        text=content_text,
                        source_message_id=msg.message_id,
                        source_email=msg.sender,
                        sender=msg.sender,
                        source_type="email_body",
                        run_id=run_id,
                        enable_ai=True,
                        llm_provider=llm,
                    )
                    all_raw_errors.extend(body_errors)

                    if msg.has_attachments and self.settings.enable_email_attachments:
                        for att in msg.attachments:
                            t_att = time.perf_counter()
                            local_path, file_hash, err = self.downloader.download(active_provider, msg.message_id, att)
                            metrics.attachment_download_ms += (time.perf_counter() - t_att) * 1000

                            att_record = AttachmentRecord(
                                id=(
                                    f"{self.gmail_connection_id}:{att.attachment_id}"
                                    if self.gmail_connection_id
                                    else att.attachment_id or f"{msg.message_id}_{run_model.attachments_processed}"
                                ),
                                message_id=state_mgr._message_id(msg.message_id),
                                tenant_id=self.tenant_id,
                                gmail_connection_id=self.gmail_connection_id,
                                filename=att.filename,
                                mime_type=att.mime_type,
                                size=att.size,
                                hash=file_hash,
                                local_path=str(local_path) if local_path else None,
                                download_status="SUCCESS" if local_path else "FAILED",
                                extraction_status="PENDING",
                            )
                            db.add(att_record)

                            if local_path and local_path.exists():
                                t_doc = time.perf_counter()
                                doc = extract_document(
                                    file_path=local_path,
                                    source_message_id=msg.message_id,
                                    mime_type=att.mime_type,
                                    file_hash=file_hash or "",
                                )
                                metrics.document_extraction_ms += (time.perf_counter() - t_doc) * 1000

                                att_record.extraction_status = doc.extraction_status
                                att_record.extraction_error = doc.error_message

                                if doc.text:
                                    att_errors = extract_error_records(
                                        text=doc.text,
                                        source_message_id=msg.message_id,
                                        source_email=msg.sender,
                                        sender=msg.sender,
                                        attachment_name=att.filename,
                                        source_type="attachment",
                                        run_id=run_id,
                                        enable_ai=True,
                                        llm_provider=llm,
                                    )
                                    all_raw_errors.extend(att_errors)
                                run_model.attachments_processed += 1

                    state_mgr.mark_message_processed(
                        message_id=msg.message_id,
                        run_id=run_id,
                        sender=msg.sender,
                        subject=msg.subject,
                        has_attachments=msg.has_attachments,
                        provider=active_provider.provider_name,
                    )
                    metrics.message_processing_ms += (time.perf_counter() - t_msg) * 1000

                # 3. DEDUPLICATE & NORMALIZE
                deduped_errors = deduplicate_errors(all_raw_errors)
                run_model.errors_extracted = len(deduped_errors)

                # 4. DETERMINISTIC MASTER REGISTRY CHECK
                t_reg = time.perf_counter()
                known_db_codes = registry_repo.codes()
                known_txt_codes = txt_reg.get_all_codes()
                master_known_codes = known_db_codes | known_txt_codes

                new_errors: list[ErrorRecord] = []
                existing_errors: list[ErrorRecord] = []

                for err in deduped_errors:
                    norm = normalize_code(err.normalized_code or err.raw_code)
                    err.normalized_code = norm
                    if norm in master_known_codes:
                        err.is_new = False
                        existing_errors.append(err)
                    else:
                        err.is_new = True
                        new_errors.append(err)

                metrics.registry_lookup_ms = (time.perf_counter() - t_reg) * 1000
                run_model.new_errors_count = len(new_errors)
                run_model.existing_errors_count = len(existing_errors)

                # Persist extracted errors in DB
                for err in deduped_errors:
                    db_err = ExtractedError(
                        run_id=run_id,
                        tenant_id=self.tenant_id,
                        gmail_connection_id=self.gmail_connection_id,
                        raw_code=err.raw_code,
                        code=err.normalized_code,
                        message=err.message,
                        context=err.context,
                        severity=str(err.severity),
                        confidence=str(err.ai_confidence),
                        source=f"{err.source_email}:{err.attachment_name or 'Body'}",
                        source_message_id=err.source_message_id,
                        source_email=err.source_email,
                        attachment_name=err.attachment_name,
                        source_type=err.source_type,
                        occurrence_count=err.occurrence_count,
                        is_new=err.is_new,
                    )
                    db.add(db_err)
                db.commit()

                # 5. AI ROOT CAUSE & GROUPING ANALYSIS
                ai_analysis = {}
                if new_errors:
                    t_ai = time.perf_counter()
                    raw_err_items = [
                        {"error_code": e.normalized_code, "message": e.message, "context": e.context}
                        for e in new_errors
                    ]
                    ai_analysis = llm.analyze_errors(raw_err_items)
                    metrics.llm_analysis_ms = (time.perf_counter() - t_ai) * 1000

                # 6. REPORT GENERATION
                t_rep = time.perf_counter()
                html_path, json_path = save_reports(
                    run=run_model,
                    new_errors=new_errors,
                    existing_errors=existing_errors,
                    ai_analysis=ai_analysis,
                    settings=self.settings,
                )
                metrics.report_generation_ms = (time.perf_counter() - t_rep) * 1000

                # 7. NOTIFICATION & MANDATORY TRANSACTION COMMIT
                t_notif = time.perf_counter()
                if new_errors:
                    ensure_connection_active()
                    alert_sent, msg_info = self.notification_service.dispatch_alert_and_commit(
                        provider=active_provider,
                        db_session=db,
                        run=run_model,
                        new_errors=new_errors,
                        html_report_path=html_path,
                    )
                    metrics.notification_ms = (time.perf_counter() - t_notif) * 1000
                    if alert_sent:
                        run_model.status = JobStatus.SUCCESS
                    else:
                        run_model.status = JobStatus.FAILED
                        run_model.error_message = f"Notification failed: {msg_info}"
                else:
                    run_model.status = JobStatus.SUCCESS
                    run_model.notification_status = "SKIPPED"
                    run_model.registry_status = "UNCHANGED"

                metrics.total_run_ms = (time.perf_counter() - start_total) * 1000
                run_model.duration_ms = metrics.total_run_ms
                run_model.completed_at = datetime.now(timezone.utc)

                db_run.status = run_model.status.value
                db_run.completed_at = run_model.completed_at
                db_run.duration_ms = run_model.duration_ms
                db_run.emails_scanned = run_model.emails_scanned
                db_run.emails_processed = run_model.emails_processed
                db_run.attachments_processed = run_model.attachments_processed
                db_run.new_codes = run_model.new_errors_count
                db_run.known_codes = run_model.existing_errors_count
                db_run.notification_status = run_model.notification_status
                db_run.registry_status = run_model.registry_status
                db_run.error_message = run_model.error_message
                db_run.tenant_id = self.tenant_id
                db_run.gmail_connection_id = self.gmail_connection_id
                db.commit()

                state_mgr.record_run_completion(run_id, is_success=(run_model.status == JobStatus.SUCCESS))
                if self.gmail_connection_id:
                    from app.database.models import GmailConnection

                    connection = db.get(GmailConnection, self.gmail_connection_id)
                    if connection:
                        connection.last_sync_at = run_model.completed_at
                        connection.updated_at = run_model.completed_at
                        if connection.status != "DISCONNECTED":
                            if getattr(active_provider, "auth_error", None) == "REAUTHORIZATION_REQUIRED":
                                connection.status = "REAUTHORIZATION_REQUIRED"
                                connection.last_error = "Your Gmail connection needs to be reauthorized."
                            elif run_model.status == JobStatus.SUCCESS:
                                connection.status = "CONNECTED"
                                connection.last_error = None
                                connection.last_successful_monitor_at = run_model.completed_at
                            else:
                                connection.status = "CONNECTED"
                                connection.last_error = "Monitoring temporarily failed. The system will retry."
                        db.commit()
                return run_model

            except Exception as e:
                db.rollback()
                metrics.total_run_ms = (time.perf_counter() - start_total) * 1000
                run_model.status = JobStatus.FAILED
                is_reauthorization = (
                getattr(active_provider, "auth_error", None)
                == "REAUTHORIZATION_REQUIRED"
                )
                run_model.error_message = (
                "Your Gmail connection needs to be reauthorized."
                if is_reauthorization
                else "Monitoring temporarily failed. The system will retry."
                if self.gmail_connection_id
                else str(e)
                )
                run_model.duration_ms = metrics.total_run_ms
                run_model.completed_at = datetime.now(timezone.utc)

                db_run = db.get(MonitoringRun, run_id)
                if db_run:
                    db_run.status = "FAILED"
                    db_run.error_message = run_model.error_message
                    db_run.completed_at = run_model.completed_at
                    db.commit()

                if self.gmail_connection_id:
                    from app.database.models import GmailConnection

                    connection = db.get(GmailConnection, self.gmail_connection_id)
                    if connection:
                        connection.last_sync_at = run_model.completed_at
                        connection.updated_at = run_model.completed_at
                        if connection.status != "DISCONNECTED":
                            connection.last_error = run_model.error_message
                            connection.status = (
                                "REAUTHORIZATION_REQUIRED"
                                if is_reauthorization
                                else "OAUTH_ERROR"
                                if getattr(active_provider, "auth_error", None)
                                else "CONNECTED"
                            )
                        db.commit()
                    logger.error("Gmail monitoring cycle failed; details are withheld from account logs.")
                else:
                    logger.error(f"Monitoring run {run_id} failed: {str(e)}", exc_info=True)
                return run_model

    async def run_async(self, run_id: Optional[str] = None) -> MonitoringRunModel:
        """Asynchronous non-blocking wrapper running CPU work in ThreadPool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.job_manager.executor,
            self.execute_monitoring_cycle,
            run_id,
        )
