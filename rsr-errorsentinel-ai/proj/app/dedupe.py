"""Deduplicate ErrorRecords by normalized code (pure function, no I/O)."""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .models import ErrorRecord, max_severity


def deduplicate(records: Iterable[ErrorRecord]) -> dict[str, ErrorRecord]:
    out: dict[str, ErrorRecord] = {}
    for rec in records:
        cur = out.get(rec.normalized_code)
        if cur is None:
            out[rec.normalized_code] = replace(rec, sources=list(rec.sources))
            continue
        cur.occurrence_count += rec.occurrence_count
        cur.first_seen_at = min(cur.first_seen_at, rec.first_seen_at)
        cur.last_seen_at = max(cur.last_seen_at, rec.last_seen_at)
        cur.severity = max_severity(cur.severity, rec.severity)
        if not cur.message and rec.message:
            cur.message = rec.message
        if cur.ai_confidence is None:
            cur.ai_confidence = rec.ai_confidence
        cur.sources = list(dict.fromkeys(cur.sources + rec.sources))
    return out
