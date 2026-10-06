from __future__ import annotations

import logging
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings, get_settings
from app.logging.logger import get_logger
from app.database.models import GmailConnection
from app.database.session import SessionLocal
from sqlalchemy import select

logger = get_logger("scheduler")

_global_scheduler: Optional[AsyncIOScheduler] = None


def create_scheduler(settings: Optional[Settings] = None) -> AsyncIOScheduler:
    """Create and configure AsyncIOScheduler with overlap prevention."""
    cfg = settings or get_settings()
    scheduler = AsyncIOScheduler()

    from app.services import MonitoringService

    service = MonitoringService(cfg)

    async def scheduled_monitor():
        if cfg.email_provider == "gmail":
            has_connections = await run_connected_gmail_accounts(cfg)
            if has_connections:
                return
        await service.run_async()

    # Overlap prevention via max_instances=1 and coalesce=True
    interval = cfg.monitor_interval_minutes or cfg.schedule_minutes or 30
    scheduler.add_job(
        scheduled_monitor,
        "interval",
        minutes=interval,
        id="monitor",
        max_instances=1,
        coalesce=True,
    )
    logger.info(f"Configured background email monitor scheduler every {interval} minute(s)")
    return scheduler


async def run_connected_gmail_accounts(settings: Settings) -> bool:
    """Run active OAuth connections independently with bounded concurrency."""
    with SessionLocal() as db:
        connections = db.scalars(select(GmailConnection)).all()
        has_saved_connections = bool(connections)
        active_connections = [
            connection for connection in connections
            if connection.status == "CONNECTED"
        ]
        snapshots = [
            {
                "id": connection.id,
                "user_id": connection.user_id,
                "email": connection.email,
                "encrypted_credentials": connection.encrypted_credentials,
                "status": connection.status,
            }
            for connection in active_connections
        ]

    if not snapshots:
        return has_saved_connections

    from app.gmail_connections import create_account_service

    semaphore = asyncio.Semaphore(settings.max_email_workers)

    async def run_one(snapshot: dict[str, str]) -> None:
        async with semaphore:
            try:
                connection = GmailConnection(**snapshot)
                service = create_account_service(connection, settings)
                run_id = (
                    f"gmail_{connection.id}_"
                    f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
                    f"{uuid.uuid4().hex[:6]}"
                )
                await service.run_async(run_id)
            except Exception:
                logger.warning(
                    "Scheduled Gmail monitoring failed for one account; other accounts will continue."
                )
                with SessionLocal() as db:
                    failed = db.get(GmailConnection, snapshot["id"])
                    if failed and failed.status != "DISCONNECTED":
                        failed.status = "OAUTH_ERROR"
                        failed.last_error = "Monitoring temporarily failed. The system will retry."
                        failed.last_sync_at = datetime.now(timezone.utc)
                        failed.updated_at = failed.last_sync_at
                        db.commit()

    await asyncio.gather(*(run_one(item) for item in snapshots))
    return True


def get_scheduler() -> AsyncIOScheduler:
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = create_scheduler()
    return _global_scheduler
