from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class JobType(str, Enum):
    EMAIL_SCAN = "EMAIL_SCAN"
    ATTACHMENT_DOWNLOAD = "ATTACHMENT_DOWNLOAD"
    DOCUMENT_EXTRACTION = "DOCUMENT_EXTRACTION"
    ERROR_ANALYSIS = "ERROR_ANALYSIS"
    REPORT_GENERATION = "REPORT_GENERATION"
    EMAIL_NOTIFICATION = "EMAIL_NOTIFICATION"
    REGISTRY_COMMIT = "REGISTRY_COMMIT"
    FULL_MONITORING_RUN = "FULL_MONITORING_RUN"


@dataclass
class JobModel:
    job_id: str
    run_id: str
    job_type: JobType
    status: JobStatus = JobStatus.PENDING
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    result: Optional[dict[str, Any]] = None


@dataclass
class RunMetrics:
    gmail_fetch_ms: float = 0.0
    message_processing_ms: float = 0.0
    attachment_download_ms: float = 0.0
    document_extraction_ms: float = 0.0
    regex_extraction_ms: float = 0.0
    llm_analysis_ms: float = 0.0
    registry_lookup_ms: float = 0.0
    report_generation_ms: float = 0.0
    notification_ms: float = 0.0
    registry_commit_ms: float = 0.0
    total_run_ms: float = 0.0


@dataclass
class MonitoringRunModel:
    run_id: str
    status: JobStatus = JobStatus.PENDING
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_ms: float = 0.0
    emails_scanned: int = 0
    emails_processed: int = 0
    attachments_processed: int = 0
    errors_extracted: int = 0
    new_errors_count: int = 0
    existing_errors_count: int = 0
    notification_status: str = "PENDING"  # PENDING, SENT, FAILED, SKIPPED (no new errors)
    registry_status: str = "PENDING"      # PENDING, COMMITTED, UNCHANGED
    error_message: Optional[str] = None
    metrics: RunMetrics = field(default_factory=RunMetrics)
    jobs: list[JobModel] = field(default_factory=list)
