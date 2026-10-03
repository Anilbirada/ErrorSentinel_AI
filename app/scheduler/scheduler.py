from __future__ import annotations

import logging
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings, get_settings
from app.logging.logger import get_logger

logger = get_logger("scheduler")

_global_scheduler: Optional[AsyncIOScheduler] = None


def create_scheduler(settings: Optional[Settings] = None) -> AsyncIOScheduler:
    """Create and configure AsyncIOScheduler with overlap prevention."""
    cfg = settings or get_settings()
    scheduler = AsyncIOScheduler()

    from app.services import MonitoringService

    service = MonitoringService(cfg)

    # Overlap prevention via max_instances=1 and coalesce=True
    interval = cfg.monitor_interval_minutes or cfg.schedule_minutes or 30
    scheduler.add_job(
        service.run_async,
        "interval",
        minutes=interval,
        id="monitor",
        max_instances=1,
        coalesce=True,
    )
    logger.info(f"Configured background email monitor scheduler every {interval} minute(s)")
    return scheduler


def get_scheduler() -> AsyncIOScheduler:
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = create_scheduler()
    return _global_scheduler
