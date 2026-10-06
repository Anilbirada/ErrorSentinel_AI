from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select

from app.config import get_settings
from app.auth.gmail_oauth import authenticated_user, request_user_id
from app.database.models import (
    AlertDelivery,
    AttachmentRecord,
    EmailRecord,
    ErrorRegistryEntry,
    ExtractedError,
    JobRecord,
    GmailConnection,
    GmailRegistryEntry,
    MonitoringRun,
)
from app.database.session import SessionLocal
from app.errors.normalizer import normalize_code
from app.jobs.manager import get_job_manager
from app.models.jobs import JobStatus, JobType
from app.registry.txt_registry import TxtRegistry
from app.services import MonitoringService, RunService

router = APIRouter(prefix="/api")


def _tenant_filter(model: Any, user_id: Optional[str]):
    return model.tenant_id == user_id if user_id else model.tenant_id.is_(None)


def serialize(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "__table__"):
        res = {}
        for c in obj.__table__.columns:
            val = getattr(obj, c.name)
            if hasattr(val, "isoformat"):
                res[c.name] = val.isoformat()
            else:
                res[c.name] = val
        return res
    return dict(obj)


@router.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "RSR ErrorSentinel AI",
    }


@router.get("/preflight")
def preflight():
    settings = get_settings()
    missing = settings.missing_graph_settings
    return {
        "status": "ready" if not missing else "incomplete",
        "missing": missing,
    }


@router.get("/config/status")
def config_status():
    settings = get_settings()
    return {
        "app_env": settings.app_env,
        "email_provider": settings.email_provider,
        "gmail_configured": settings.gmail_ready,
        "google_oauth_configured": settings.google_oauth_ready,
        "graph_configured": settings.graph_ready,
        "llm_provider": settings.active_llm_provider,
        "llm_model": settings.active_llm_model,
        "max_email_workers": settings.max_email_workers,
        "max_attachment_workers": settings.max_attachment_workers,
        "max_llm_concurrency": settings.max_llm_concurrency,
        "monitor_interval_minutes": settings.monitor_interval_minutes,
        "database_configured": bool(settings.database_url),
    }


@router.get("/status")
def status_endpoint(request: Request):
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        last = db.scalar(
            select(MonitoringRun)
            .where(_tenant_filter(MonitoringRun, user_id))
            .order_by(desc(MonitoringRun.started_at))
            .limit(1)
        )
        job_mgr = get_job_manager()
        is_running = any(
            j.status == JobStatus.RUNNING
            and (j.tenant_id == user_id if user_id else j.tenant_id is None)
            for j in job_mgr.active_jobs.values()
        )
        return {
            "monitoring": "RUNNING" if is_running else "IDLE",
            "last_run": serialize(last) if last else None,
            "provider": get_settings().email_provider,
            "graph_configured": get_settings().graph_ready,
        }
    finally:
        db.close()


@router.post("/run-now", status_code=status.HTTP_202_ACCEPTED)
async def run_now(request: Request, x_csrf_token: str | None = Header(default=None)):
    settings = get_settings()
    user_id = request_user_id(request)
    if user_id:
        authenticated_user(request)
        from app.auth.gmail_oauth import verify_csrf

        verify_csrf(request, x_csrf_token)
        with SessionLocal() as db:
            connections = db.scalars(
                select(GmailConnection).where(
                    GmailConnection.user_id == user_id,
                    GmailConnection.status == "CONNECTED",
                )
            ).all()
            if not connections:
                raise HTTPException(
                    status_code=409,
                    detail="Connect a Gmail account before starting monitoring.",
                )
            started = []
            job_mgr = get_job_manager()
            for connection in connections:
                active_run = db.scalar(
                    select(MonitoringRun.id).where(
                        MonitoringRun.gmail_connection_id == connection.id,
                        MonitoringRun.status == "RUNNING",
                    )
                )
                active_job = db.scalar(
                    select(JobRecord.id).where(
                        JobRecord.gmail_connection_id == connection.id,
                        JobRecord.status.in_(("PENDING", "RUNNING")),
                    )
                )
                if active_run or active_job:
                    continue
                from app.gmail_connections import (
                    create_account_service,
                    execute_tracked_monitoring,
                )

                service = create_account_service(connection, settings)
                run_id = (
                    f"gmail_{connection.id}_"
                    f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
                    f"{uuid.uuid4().hex[:6]}"
                )
                job = job_mgr.create_job(
                    run_id,
                    JobType.FULL_MONITORING_RUN,
                    tenant_id=user_id,
                    gmail_connection_id=connection.id,
                )
                job_mgr.submit_task(
                    execute_tracked_monitoring,
                    service,
                    run_id,
                    job.job_id,
                )
                started.append(
                    {"connection_id": connection.id, "run_id": run_id, "job_id": job.job_id}
                )
            if not started:
                return {
                    "status": "already_running",
                    "message": "Monitoring is already running for all connected Gmail accounts.",
                }
            return {
                "status": "accepted",
                "jobs": started,
                "job_id": started[0]["job_id"],
                "message": "Monitoring started for connected Gmail accounts.",
            }

    if settings.email_provider == "microsoft_graph" and settings.missing_graph_settings:
        raise HTTPException(
            503,
            detail={
                "error": "Microsoft Graph configuration is incomplete",
                "missing": settings.missing_graph_settings,
            },
        )

    if settings.missing_graph_settings and settings.ms_tenant_id:
        raise HTTPException(
            503,
            detail={
                "error": "Microsoft Graph configuration is incomplete",
                "missing": settings.missing_graph_settings,
            },
        )

    job_mgr = get_job_manager()
    if job_mgr.is_cycle_active():
        return {
            "status": "already_running",
            "message": "A monitoring run is already in progress.",
        }

    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    job = job_mgr.create_job(run_id, JobType.FULL_MONITORING_RUN)

    service = MonitoringService(settings)
    job_mgr.submit_task(service.execute_monitoring_cycle, run_id)

    return {
        "status": "accepted",
        "job_id": job.job_id,
        "run_id": run_id,
        "message": "Monitoring run enqueued in background.",
    }


@router.get("/runs")
def list_runs(request: Request, limit: int = 50):
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        limit_val = int(limit) if not isinstance(limit, int) else limit
        runs = db.scalars(
            select(MonitoringRun)
            .where(_tenant_filter(MonitoringRun, user_id))
            .order_by(desc(MonitoringRun.started_at))
            .limit(limit_val)
        ).all()
        return [serialize(r) for r in runs]
    finally:
        db.close()


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        item = db.scalar(
            select(MonitoringRun).where(
                MonitoringRun.id == run_id,
                _tenant_filter(MonitoringRun, user_id),
            )
        )
        if not item:
            raise HTTPException(404, detail=f"Run '{run_id}' not found")
        return serialize(item)
    finally:
        db.close()


@router.get("/runs/{run_id}/deliveries")
def run_deliveries(run_id: str, request: Request):
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        if db.scalar(
            select(MonitoringRun).where(
                MonitoringRun.id == run_id,
                _tenant_filter(MonitoringRun, user_id),
            )
        ) is None:
            raise HTTPException(404, detail="Run not found")
        deliveries = db.scalars(
            select(AlertDelivery)
            .where(
                AlertDelivery.run_id == run_id,
                _tenant_filter(AlertDelivery, user_id),
            )
            .order_by(AlertDelivery.sent_at, AlertDelivery.id)
        ).all()
        return [
            {
                "status": item.status,
                "sent_at": item.sent_at.isoformat() if item.sent_at else None,
                "error": item.error,
            }
            for item in deliveries
        ]
    finally:
        db.close()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    user_id = request_user_id(request)
    job_mgr = get_job_manager()
    if job_id in job_mgr.active_jobs:
        job = job_mgr.active_jobs[job_id]
        if (job.tenant_id == user_id if user_id else job.tenant_id is None):
            return job.__dict__
        raise HTTPException(status_code=404, detail="Job not found")

    db = SessionLocal()
    try:
        db_job = db.scalar(
            select(JobRecord).where(
                JobRecord.id == job_id,
                _tenant_filter(JobRecord, user_id),
            )
        )
        if not db_job:
            raise HTTPException(404, detail=f"Job '{job_id}' not found")
        return serialize(db_job)
    finally:
        db.close()


@router.get("/errors")
def list_errors(
    request: Request,
    new_only: bool = False,
    limit: int = 200,
):
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        limit_val = int(limit) if not isinstance(limit, int) else limit
        stmt = (
            select(ExtractedError)
            .where(_tenant_filter(ExtractedError, user_id))
            .order_by(desc(ExtractedError.id))
            .limit(limit_val)
        )
        records = db.scalars(stmt).all()
        if user_id:
            connection_ids = db.scalars(
                select(GmailConnection.id).where(GmailConnection.user_id == user_id)
            ).all()
            registry = set(
                db.scalars(
                    select(GmailRegistryEntry.code).where(
                        GmailRegistryEntry.connection_id.in_(connection_ids)
                    )
                ).all()
            ) if connection_ids else set()
        else:
            registry = {x.code for x in db.scalars(select(ErrorRegistryEntry)).all()}
            registry |= TxtRegistry(get_settings().registry_file).get_all_codes()

        if user_id and new_only:
            return [serialize(record) for record in records if record.is_new]
        return [serialize(x) for x in records if not new_only or x.code not in registry]
    finally:
        db.close()


@router.get("/errors/new")
def list_new_errors(request: Request):
    return list_errors(request, new_only=True)


@router.get("/errors/{code}")
def get_error_details(code: str, request: Request):
    user_id = request_user_id(request)
    norm = normalize_code(code)
    db = SessionLocal()
    try:
        if user_id:
            connection_ids = db.scalars(
                select(GmailConnection.id).where(GmailConnection.user_id == user_id)
            ).all()
            registry_entry = db.scalar(
                select(GmailRegistryEntry).where(
                    GmailRegistryEntry.code == norm,
                    GmailRegistryEntry.connection_id.in_(connection_ids),
                )
            ) if connection_ids else None
        else:
            registry_entry = db.scalar(select(ErrorRegistryEntry).where(ErrorRegistryEntry.code == norm))
        occurrences = db.scalars(
            select(ExtractedError).where(
                ExtractedError.code == norm,
                _tenant_filter(ExtractedError, user_id),
            )
        ).all()

        return {
            "code": norm,
            "in_registry": registry_entry is not None,
            "registry_details": serialize(registry_entry) if registry_entry else None,
            "total_occurrences": sum(o.occurrence_count for o in occurrences) if occurrences else 0,
            "history": [serialize(o) for o in occurrences],
        }
    finally:
        db.close()


@router.get("/metrics")
def get_metrics(request: Request):
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        recent_runs = db.scalars(
            select(MonitoringRun)
            .where(
                MonitoringRun.status == "SUCCESS",
                _tenant_filter(MonitoringRun, user_id),
            )
            .order_by(desc(MonitoringRun.started_at))
            .limit(10)
        ).all()

        durations = [r.duration_ms for r in recent_runs if r.duration_ms > 0]
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        return {
            "average_run_duration_ms": round(avg_duration, 2),
            "recent_durations_ms": durations,
            "total_emails_scanned": db.scalar(
                select(func.coalesce(func.sum(MonitoringRun.emails_scanned), 0)).where(
                    _tenant_filter(MonitoringRun, user_id)
                )
            ),
            "total_attachments_processed": db.scalar(
                select(func.coalesce(func.sum(MonitoringRun.attachments_processed), 0)).where(
                    _tenant_filter(MonitoringRun, user_id)
                )
            ),
            "registered_unique_codes": (
                db.scalar(
                    select(func.count())
                    .select_from(GmailRegistryEntry)
                    .where(
                        GmailRegistryEntry.connection_id.in_(
                            select(GmailConnection.id).where(GmailConnection.user_id == user_id)
                        )
                    )
                )
                if user_id
                else db.scalar(select(func.count(ErrorRegistryEntry.id)))
            ),
        }
    finally:
        db.close()


@router.get("/stats")
def stats(request: Request):
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        return {
            "runs": db.scalar(
                select(func.count()).select_from(MonitoringRun).where(
                    _tenant_filter(MonitoringRun, user_id)
                )
            ) or 0,
            "successful_runs": db.scalar(
                select(func.count())
                .select_from(MonitoringRun)
                .where(
                    MonitoringRun.status == "SUCCESS",
                    _tenant_filter(MonitoringRun, user_id),
                )
            ) or 0,
            "emails_processed": db.scalar(
                select(func.coalesce(func.sum(MonitoringRun.emails_processed), 0)).where(
                    _tenant_filter(MonitoringRun, user_id)
                )
            ) or 0,
            "new_codes": (
                db.scalar(
                    select(func.count())
                    .select_from(GmailRegistryEntry)
                    .where(
                        GmailRegistryEntry.connection_id.in_(
                            select(GmailConnection.id).where(GmailConnection.user_id == user_id)
                        )
                    )
                )
                if user_id
                else db.scalar(select(func.count()).select_from(ErrorRegistryEntry))
            ) or 0,
            "alerts_sent": db.scalar(
                select(func.count())
                .select_from(AlertDelivery)
                .where(
                    AlertDelivery.status == "SUCCESS",
                    _tenant_filter(AlertDelivery, user_id),
                )
            ) or 0,
        }
    finally:
        db.close()


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_alias(request: Request, x_csrf_token: str | None = Header(default=None)):
    """Alias for /run-now to support webhook and direct customer triggering."""
    return await run_now(request, x_csrf_token)


@router.get("/registry")
def list_registry(request: Request, limit: int = 500):
    """List master error registry entries with stats."""
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        if user_id:
            connection_ids = db.scalars(
                select(GmailConnection.id).where(GmailConnection.user_id == user_id)
            ).all()
            entries = db.scalars(
                select(GmailRegistryEntry)
                .where(GmailRegistryEntry.connection_id.in_(connection_ids))
                .order_by(desc(GmailRegistryEntry.last_seen_at))
                .limit(limit)
            ).all() if connection_ids else []
            return [
                {
                    "code": entry.code,
                    "occurrence_count": entry.occurrence_count,
                    "first_seen_at": entry.first_seen_at.isoformat(),
                    "last_seen_at": entry.last_seen_at.isoformat(),
                    "connection_id": entry.connection_id,
                }
                for entry in entries
            ]
        entries = db.scalars(
            select(ErrorRegistryEntry).order_by(desc(ErrorRegistryEntry.last_seen_at)).limit(limit)
        ).all()
        return [serialize(e) for e in entries]
    finally:
        db.close()


@router.get("/export/csv")
def export_registry_csv(request: Request):
    """Export error registry as CSV."""
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        if user_id:
            connection_ids = db.scalars(
                select(GmailConnection.id).where(GmailConnection.user_id == user_id)
            ).all()
            entries = db.scalars(
                select(GmailRegistryEntry)
                .where(GmailRegistryEntry.connection_id.in_(connection_ids))
                .order_by(GmailRegistryEntry.code)
            ).all() if connection_ids else []
        else:
            entries = db.scalars(select(ErrorRegistryEntry).order_by(ErrorRegistryEntry.code)).all()
        lines = ["code,occurrences,first_seen_at,last_seen_at,status,source"]
        for e in entries:
            f_seen = e.first_seen_at.isoformat() if e.first_seen_at else ""
            l_seen = e.last_seen_at.isoformat() if e.last_seen_at else ""
            status_value = getattr(e, "status", "ACTIVE")
            source_value = getattr(e, "source", "gmail_monitor")
            lines.append(f'"{e.code}",{e.occurrence_count},"{f_seen}","{l_seen}","{status_value}","{source_value}"')
        csv_content = "\n".join(lines)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=error_registry.csv"},
        )
    finally:
        db.close()


@router.get("/export/txt")
def export_registry_txt(request: Request):
    """Export error registry as plain text (compatible with existing_error_codes.txt)."""
    settings = get_settings()
    user_id = request_user_id(request)
    if user_id:
        with SessionLocal() as db:
            connection_ids = db.scalars(
                select(GmailConnection.id).where(GmailConnection.user_id == user_id)
            ).all()
            codes = sorted(
                set(
                    db.scalars(
                        select(GmailRegistryEntry.code).where(
                            GmailRegistryEntry.connection_id.in_(connection_ids)
                        )
                    ).all()
                )
            ) if connection_ids else []
    else:
        txt_reg = TxtRegistry(settings.registry_file)
        codes = sorted(txt_reg.get_all_codes())
    content = "\n".join(codes) + "\n"
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=existing_error_codes.txt"},
    )


@router.get("/attachments")
def list_attachments(request: Request, limit: int = 100):
    """List processed attachments with extraction metadata."""
    user_id = request_user_id(request)
    db = SessionLocal()
    try:
        records = db.scalars(
            select(AttachmentRecord)
            .where(_tenant_filter(AttachmentRecord, user_id))
            .order_by(desc(AttachmentRecord.id))
            .limit(limit)
        ).all()
        return [serialize(a) for a in records]
    finally:
        db.close()


@router.get("/system/health")
def detailed_health():
    """Enterprise component health monitoring."""
    settings = get_settings()
    db_healthy = False
    try:
        db = SessionLocal()
        db.execute(select(1))
        db.close()
        db_healthy = True
    except Exception:
        db_healthy = False

    job_mgr = get_job_manager()
    return {
        "overall": "HEALTHY" if db_healthy else "DEGRADED",
        "components": {
            "database": {"status": "HEALTHY" if db_healthy else "ERROR", "type": "SQLite ACID"},
            "provider": {
                "active": settings.email_provider,
                "gmail_ready": settings.gmail_ready,
                "graph_ready": settings.graph_ready,
                "status": "HEALTHY" if (settings.email_provider == "gmail" and settings.gmail_ready) or (settings.email_provider == "microsoft_graph" and settings.graph_ready) or (settings.email_provider == "demo") else "WARNING",
            },
            "ai_engine": {
                "provider": settings.active_llm_provider,
                "model": settings.active_llm_model,
                "status": "HEALTHY",
            },
            "scheduler": {
                "interval_minutes": settings.monitor_interval_minutes,
                "status": "HEALTHY",
            },
            "workers": {
                "email_workers": settings.max_email_workers,
                "attachment_workers": settings.max_attachment_workers,
                "llm_concurrency": settings.max_llm_concurrency,
                "status": "HEALTHY",
            },
            "transaction_enforcer": {
                "rule": "ALERT_FIRST_THEN_COMMIT",
                "status": "HEALTHY",
            }
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/events")
async def events_sse(request: Request):
    """Server-Sent Events endpoint streaming live job and run updates."""
    queue = asyncio.Queue()
    job_mgr = get_job_manager()
    job_mgr.register_subscriber(queue)
    user_id = request_user_id(request)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'event': 'connected', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
            while True:
                msg = await queue.get()
                event_tenant = msg.get("tenant_id")
                if user_id and event_tenant != user_id:
                    continue
                if not user_id and event_tenant is not None:
                    continue
                yield f"data: {json.dumps(msg, default=str)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            job_mgr.unregister_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
