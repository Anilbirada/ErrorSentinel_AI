from __future__ import annotations

from typing import Iterable, Any
from app.models.extraction import ErrorRecord
from app.errors.extractor import ErrorFinding


def deduplicate(findings: Iterable[ErrorFinding]) -> dict[str, dict[str, Any]]:
    """
    Legacy deduplication helper returning dict mapping normalized code to finding group.
    """
    groups: dict[str, dict[str, Any]] = {}
    for f in findings:
        if not f.code:
            continue
        if f.code not in groups:
            groups[f.code] = {
                "finding": f,
                "occurrences": 1,
                "sources": {f.source} if f.source else set(),
            }
        else:
            groups[f.code]["occurrences"] += 1
            if f.source:
                groups[f.code]["sources"].add(f.source)
    return groups


def deduplicate_errors(errors: Iterable[ErrorRecord]) -> list[ErrorRecord]:
    """
    Deduplicate errors within a single run by their normalized_code.
    Aggregates occurrence_count, merges unique contexts/sources,
    and preserves the highest severity and AI confidence.
    """
    severity_rank = {
        "CRITICAL": 5,
        "HIGH": 4,
        "MEDIUM": 3,
        "LOW": 2,
        "INFO": 1,
    }

    seen: dict[str, ErrorRecord] = {}

    for err in errors:
        code = err.normalized_code
        if not code:
            continue

        if code not in seen:
            seen[code] = ErrorRecord(
                raw_code=err.raw_code,
                normalized_code=code,
                message=err.message,
                context=err.context,
                severity=err.severity,
                source_message_id=err.source_message_id,
                source_email=err.source_email,
                sender=err.sender,
                attachment_name=err.attachment_name,
                source_type=err.source_type,
                occurrence_count=err.occurrence_count or 1,
                first_seen_at=err.first_seen_at,
                last_seen_at=err.last_seen_at,
                ai_confidence=err.ai_confidence,
                run_id=err.run_id,
                is_new=err.is_new,
                ai_interpretation=err.ai_interpretation,
            )
        else:
            existing = seen[code]
            existing.occurrence_count += (err.occurrence_count or 1)

            # Preserve latest timestamp
            if err.last_seen_at > existing.last_seen_at:
                existing.last_seen_at = err.last_seen_at

            # Merge context if new
            if err.context and err.context not in existing.context:
                existing.context = f"{existing.context}\n---\n{err.context}".strip()

            # Merge messages if informative
            if err.message and err.message not in existing.message:
                existing.message = f"{existing.message}; {err.message}"

            # Highest severity
            existing_rank = severity_rank.get(str(existing.severity).upper(), 3)
            new_rank = severity_rank.get(str(err.severity).upper(), 3)
            if new_rank > existing_rank:
                existing.severity = err.severity

            # Confidence
            existing.ai_confidence = max(existing.ai_confidence, err.ai_confidence)

    return list(seen.values())
