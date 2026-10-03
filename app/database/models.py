from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.session import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid.uuid4())


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    status: Mapped[str] = mapped_column(String(30), index=True, default="PENDING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    emails_scanned: Mapped[int] = mapped_column(Integer, default=0)
    emails_processed: Mapped[int] = mapped_column(Integer, default=0)
    attachments_processed: Mapped[int] = mapped_column(Integer, default=0)
    new_codes: Mapped[int] = mapped_column(Integer, default=0)
    known_codes: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    notification_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    registry_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")


class EmailRecord(Base):
    __tablename__ = "email_records"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    internet_message_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sender: Mapped[str] = mapped_column(String(320), default="")
    recipients: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(50), default="gmail")
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(30), index=True, default="pending")
    run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("monitoring_runs.id"), nullable=True)

    __table_args__ = (
        Index("ix_email_processed", "processed_at"),
        Index("ix_email_status", "processing_status"),
    )


class AttachmentRecord(Base):
    __tablename__ = "attachment_records"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("email_records.id"), index=True)
    filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(255), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    download_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    extraction_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    extraction_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExtractedError(Base):
    __tablename__ = "extracted_errors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("monitoring_runs.id"), index=True)
    raw_code: Mapped[str] = mapped_column(String(255), default="")
    code: Mapped[str] = mapped_column(String(255), index=True)  # normalized code
    message: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    confidence: Mapped[str] = mapped_column(String(10), default="1.0")
    source: Mapped[str] = mapped_column(Text, default="")
    source_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    attachment_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), default="email_body")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_interpretation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ErrorRegistryEntry(Base):
    __tablename__ = "error_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    source: Mapped[str] = mapped_column(String(100), default="email_monitor")
    source_run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (
        Index("ix_registry_code", "code"),
        Index("ix_registry_created", "created_at"),
        Index("ix_registry_status", "status"),
    )


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("monitoring_runs.id"), index=True)
    recipient: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_path: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    job_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True, default="PENDING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ProcessingStateRecord(Base):
    __tablename__ = "processing_state"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    level: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
