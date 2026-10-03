"""Offline demo: no Gmail, no Graph, no external LLM."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .config import Settings
from .database import Database
from .models import EmailMessage, RunResult
from .normalization import Normalizer
from .pipeline import Pipeline
from .providers.memory import MemoryProvider
from .registry import Registry

LOG_V1 = "ERR-5021 Database connection timeout\nERR-7788 Payment gateway timeout\n"
LOG_V2 = LOG_V1 + "ERR-9001 API authentication failure\n"


def build_demo(workdir: Path) -> tuple[Pipeline, MemoryProvider, Registry]:
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    settings = Settings(email_provider="memory", database_url=f"sqlite:///{workdir / 'app.db'}",
                        report_output_dir=str(workdir / "reports"), log_dir=str(workdir / "logs"),
                        alert_recipients=["ops@example.test"], notify_backoff_s=0.0, notify_retries=2)
    db = Database(settings.sqlite_path)
    registry = Registry(db, Normalizer())
    provider = MemoryProvider()
    return Pipeline(settings, db, registry, provider), provider, registry


def run_demo(workdir: str | Path = "demo_workspace", out: Callable[[str], None] = print) -> list[RunResult]:
    pipeline, provider, registry = build_demo(Path(workdir))
    base = datetime.now(timezone.utc) - timedelta(minutes=5)
    n = 0

    def email(log_text: str, minutes: int) -> None:
        nonlocal n
        n += 1
        provider.add_message(EmailMessage(f"demo-{n}", "monitor@client.example", "Production Errors",
                                          base + timedelta(minutes=minutes), body_text="See attached log."),
                             [("production.log", "text/plain", log_text.encode())])

    results: list[RunResult] = []

    def step(title: str, expect: str) -> RunResult:
        r = pipeline.run()
        results.append(r)
        out(f"\n== {title}\n   expected: {expect}\n   emails processed={r.emails_processed} "
            f"new={r.new_codes} existing={r.existing_codes}\n   alert={r.notification_status} "
            f"registry={r.registry_status} -> {registry.all_codes()}")
        return r

    email(LOG_V1, 0)
    step("1. First email: ERR-5021, ERR-7788", "2 NEW, alert sent, both committed")
    email(LOG_V1, 1)
    step("2. Same content again in a new email", "0 NEW, no alert")
    email(LOG_V2, 2)
    provider.fail_sends = True
    step("3. ERR-9001 appears, alert delivery FAILS", "1 NEW, registry unchanged (no ERR-9001)")
    provider.fail_sends = False
    step("4. Retry with delivery working", "ERR-9001 alerted and committed")
    step("5. Run again with nothing new", "0 NEW, no duplicate registry entries")
    out(f"\nAlerts delivered: {len(provider.outbox)}; reports in {Path(workdir) / 'reports'}")
    return results
