from __future__ import annotations

from ..config import Settings
from .base import EmailProvider
from .memory import MemoryProvider


def build_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider == "memory":
        return MemoryProvider()
    raise NotImplementedError(
        f"EMAIL_PROVIDER={settings.email_provider!r} is not implemented yet. "
        "The Gmail provider is the next stage; Microsoft Graph follows. Use --demo for now.")
