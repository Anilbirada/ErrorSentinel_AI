from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.database import Database
from app.normalization import Normalizer
from app.pipeline import Pipeline
from app.providers.memory import MemoryProvider
from app.registry import Registry

T0 = datetime.now(timezone.utc) - timedelta(minutes=30)


@pytest.fixture
def settings(tmp_path):
    return Settings(email_provider="memory", database_url=f"sqlite:///{tmp_path / 'app.db'}",
                    report_output_dir=str(tmp_path / "reports"), log_dir=str(tmp_path / "logs"),
                    alert_recipients=["ops@example.test"], notify_backoff_s=0.0, notify_retries=2)


@pytest.fixture
def env(settings):
    from app.models import EmailMessage  # noqa: F401
    db = Database(settings.sqlite_path)
    registry = Registry(db, Normalizer())
    provider = MemoryProvider()
    pipeline = Pipeline(settings, db, registry, provider)
    return type("Env", (), dict(settings=settings, db=db, registry=registry, provider=provider, pipeline=pipeline))


_counter = {"n": 0}


def add_email(provider, body="", attachments=None, subject="Errors", sender="a@x.test", minutes=0):
    from app.models import EmailMessage
    _counter["n"] += 1
    mid = f"m{_counter['n']}"
    provider.add_message(EmailMessage(mid, sender, subject, datetime.now(timezone.utc) + timedelta(milliseconds=_counter["n"]),
                                      body_text=body), attachments or [])
    return mid
