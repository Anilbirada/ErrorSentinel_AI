from __future__ import annotations

from typing import Optional
from app.config import Settings, get_settings
from app.providers.base import EmailProvider
from app.providers.gmail.provider import GmailProvider
from app.providers.microsoft_graph.provider import MicrosoftGraphProvider
from app.providers.demo.provider import DemoEmailProvider


def get_email_provider(
    provider_name: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> EmailProvider:
    config = settings or get_settings()
    p_name = (provider_name or config.email_provider).lower()

    if p_name in ("gmail", "google"):
        return GmailProvider(config)
    elif p_name in ("microsoft_graph", "graph", "outlook", "ms365"):
        return MicrosoftGraphProvider(config)
    elif p_name in ("demo", "mock", "test"):
        return DemoEmailProvider(config)
    else:
        # Default fallback
        return DemoEmailProvider(config)
