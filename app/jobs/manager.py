from __future__ import annotations

import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.config import Settings, get_settings
from app.database.models import JobRecord
from app.database.session import SessionLocal
from app.logging.logger import get_logger
from app.models.jobs import JobModel, JobStatus, JobType

logger = get_logger("job_manager")


class JobManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(JobManager, cls).__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        self.settings = get_settings()
        self.executor = ThreadPoolExecutor(
            max_workers=max(self.settings.max_email_workers, self.settings.max_attachment_workers, 10),
            thread_name_prefix="sentinel_worker",
        )
        self.active_jobs: dict[str, JobModel] = {}
        self.subscribers: list[asyncio.Queue] = []
        self._is_running_cycle = False
        self._run_lock = threading.Lock()

    def is_cycle_active(self) -> bool:
        return self._is_running_cycle

    def create_job(
        self,
        run_id: str,
        job_type: JobType,
        tenant_id: Optional[str] = None,
        gmail_connection_id: Optional[str] = None,
    ) -> JobModel:
        job_id = f"job_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        model = JobModel(
            job_id=job_id,
            run_id=run_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            started_at=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            gmail_connection_id=gmail_connection_id,
        )
        self.active_jobs[job_id] = model

        # Persist to database
        try:
            with SessionLocal() as db:
                db_job = JobRecord(
                    id=job_id,
                    tenant_id=tenant_id,
                    gmail_connection_id=gmail_connection_id,
                    run_id=run_id,
                    job_type=job_type.value,
                    status=JobStatus.PENDING.value,
                    started_at=model.started_at,
                )
                db.add(db_job)
                db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist initial job {job_id}: {str(e)}")

        self.broadcast_event(
            {
                "event": "job_created",
                "job": model.__dict__,
                "tenant_id": tenant_id,
                "gmail_connection_id": gmail_connection_id,
            }
        )
        return model

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: Optional[str] = None,
        result: Optional[dict[str, Any]] = None,
    ):
        if job_id in self.active_jobs:
            job = self.active_jobs[job_id]
            job.status = status
            if error_message:
                job.error_message = error_message
            if result:
                job.result = result
            if status in (JobStatus.SUCCESS, JobStatus.FAILED):
                job.completed_at = datetime.now(timezone.utc)

        # Update DB
        try:
            with SessionLocal() as db:
                db_job = db.get(JobRecord, job_id)
                if db_job:
                    db_job.status = status.value
                    if error_message:
                        db_job.error_message = error_message
                    if status in (JobStatus.SUCCESS, JobStatus.FAILED):
                        db_job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception as e:
            logger.warning(f"Failed updating job status in DB: {str(e)}")

        self.broadcast_event({
            "event": "job_updated",
            "job_id": job_id,
            "status": status.value,
            "error": error_message,
            "tenant_id": (
                self.active_jobs[job_id].tenant_id
                if job_id in self.active_jobs
                else None
            ),
            "gmail_connection_id": (
                self.active_jobs[job_id].gmail_connection_id
                if job_id in self.active_jobs
                else None
            ),
        })

    def submit_task(self, fn: Callable, *args, **kwargs):
        """Submit background worker task to bounded thread pool."""
        return self.executor.submit(fn, *args, **kwargs)

    def broadcast_event(self, message: dict[str, Any]):
        """Publish event to all connected dashboard SSE streams."""
        # Non-blocking broadcast
        dead_queues = []
        for q in self.subscribers:
            try:
                q.put_nowait(message)
            except Exception:
                dead_queues.append(q)
        for dead in dead_queues:
            if dead in self.subscribers:
                self.subscribers.remove(dead)

    def register_subscriber(self, q: asyncio.Queue):
        if q not in self.subscribers:
            self.subscribers.append(q)

    def unregister_subscriber(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)


_job_manager = None


def get_job_manager() -> JobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager
