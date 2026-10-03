from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class RegistryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    MUTED = "MUTED"


class RegistryDecision(str, Enum):
    NEW = "NEW"
    EXISTING = "EXISTING"


@dataclass
class RegistryEntry:
    id: Optional[int] = None
    normalized_code: str = ""
    first_seen_at: datetime = field(default_factory=now_utc)
    last_seen_at: datetime = field(default_factory=now_utc)
    occurrence_count: int = 1
    status: RegistryStatus = RegistryStatus.ACTIVE
    source: str = "email_monitor"
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)
