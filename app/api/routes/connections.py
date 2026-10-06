from __future__ import annotations

from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import desc, func, select

from app.auth.gmail_oauth import (
    authenticated_user,
    connection_for_user,
    verify_csrf,
)
from app.config import get_settings
from app.database.models import AlertDelivery, GmailConnection, JobRecord, MonitoringRun
from app.database.session import SessionLocal
from app.jobs.manager import get_job_manager
from app.models.jobs import JobType
from app.gmail_connections import create_account_service, execute_tracked_monitoring

router = APIRouter(prefix="/api/gmail-connections", tags=["gmail-connections"])


@router.get("")
def list_gmail_connections(request: Request):
    user = authenticated_user(request)
    with SessionLocal() as db:
        connections = db.scalars(
            select(GmailConnection)
            .where(GmailConnection.user_id == user.id)
            .order_by(desc(GmailConnection.created_at))
        ).all()
        response = []
        for connection in connections:
            run_stats = db.execute(
                select(
                    func.coalesce(func.sum(MonitoringRun.emails_processed), 0),
                    func.coalesce(func.sum(MonitoringRun.new_codes), 0),
                    func.coalesce(func.sum(MonitoringRun.known_codes), 0),
                ).where(MonitoringRun.gmail_connection_id == connection.id)
            ).one()
            is_running = db.scalar(
                select(MonitoringRun.id)
                .where(
                    MonitoringRun.gmail_connection_id == connection.id,
                    MonitoringRun.status == "RUNNING",
                )
                .limit(1)
            )
            alerts_sent = db.scalar(
                select(func.count())
                .select_from(AlertDelivery)
                .where(
                    AlertDelivery.gmail_connection_id == connection.id,
                    AlertDelivery.status == "SUCCESS",
                )
            ) or 0
            response.append(
                {
                    "id": connection.id,
                    "email": connection.email,
                    "status": connection.status,
                    "created_at": connection.created_at.isoformat(),
                    "updated_at": connection.updated_at.isoformat(),
                    "last_sync_at": connection.last_sync_at.isoformat() if connection.last_sync_at else None,
                    "last_successful_monitor_at": (
                        connection.last_successful_monitor_at.isoformat()
                        if connection.last_successful_monitor_at
                        else None
                    ),
                    "last_error": connection.last_error,
                    "monitoring": "RUNNING" if is_running else "IDLE",
                    "emails_processed": int(run_stats[0] or 0),
                    "new_errors": int(run_stats[1] or 0),
                    "existing_errors": int(run_stats[2] or 0),
                    "alerts_sent": alerts_sent,
                }
            )
        return response


@router.post("/{connection_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_gmail_monitoring(
    connection_id: str,
    request: Request,
    x_csrf_token: str | None = Header(default=None),
):
    user = authenticated_user(request)
    verify_csrf(request, x_csrf_token)
    with SessionLocal() as db:
        connection = connection_for_user(
            db,
            connection_id=connection_id,
            user_id=user.id,
        )
        if connection.status != "CONNECTED":
            raise HTTPException(
                status_code=409,
                detail="Your Gmail connection needs to be reauthorized.",
            )
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
            return {
                "status": "already_running",
                "run_id": active_run,
                "job_id": active_job,
            }
        service = create_account_service(connection)
        run_id = (
            f"gmail_{connection.id}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
            f"{uuid.uuid4().hex[:6]}"
        )
        job_manager = get_job_manager()
        job = job_manager.create_job(
            run_id,
            JobType.FULL_MONITORING_RUN,
            tenant_id=user.id,
            gmail_connection_id=connection.id,
        )
        job_manager.submit_task(execute_tracked_monitoring, service, run_id, job.job_id)
        return {
            "status": "accepted",
            "run_id": run_id,
            "job_id": job.job_id,
        }
