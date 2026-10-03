from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.ai.provider import LLMProvider, get_llm_provider
from app.errors.normalizer import normalize_code
from app.errors.patterns import DEFAULT_PATTERNS
from app.logging.logger import get_logger
from app.models.extraction import ErrorRecord, SeverityLevel

logger = get_logger("error_extractor")


@dataclass(frozen=True)
class ErrorFinding:
    """Compatibility finding object for legacy unit tests."""
    code: str
    message: str
    context: str
    severity: str = "UNKNOWN"
    confidence: float = 1.0
    source: str = ""


def _infer_severity(context_text: str) -> SeverityLevel:
    lower = context_text.lower()
    if any(k in lower for k in ["fatal", "critical", "emergency", "panic", "outage", "system down"]):
        return SeverityLevel.CRITICAL
    elif any(k in lower for k in ["timeout", "deadlock", "auth failure", "refused", "500", "database failed"]):
        return SeverityLevel.HIGH
    elif any(k in lower for k in ["warn", "warning", "retry", "404", "invalid", "deprecated"]):
        return SeverityLevel.LOW
    elif any(k in lower for k in ["info", "notice"]):
        return SeverityLevel.INFO
    return SeverityLevel.MEDIUM


def extract_errors(
    text: str,
    source: str = "",
    patterns: Optional[list[str]] = None,
) -> list[ErrorFinding]:
    """
    Deterministic Stage 1 regex extraction returning ErrorFinding list.
    Captures all occurrences so deduplicator can aggregate counts accurately.
    """
    if not text:
        return []

    pattern_list = patterns or DEFAULT_PATTERNS
    found: list[ErrorFinding] = []

    for pattern in pattern_list:
        try:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                raw = match.group(0).strip()
                normalized = normalize_code(raw)
                if not normalized:
                    continue

                # Extract surrounding context window
                start = max(0, match.start() - 160)
                end = min(len(text), match.end() + 240)
                context = text[start:end].strip()

                sev = _infer_severity(context)
                found.append(
                    ErrorFinding(
                        code=normalized,
                        message=raw,
                        context=context,
                        severity=sev.value,
                        confidence=1.0,
                        source=source,
                    )
                )
        except Exception as e:
            logger.error(f"Error executing regex pattern '{pattern}': {str(e)}")

    return found


def extract_error_records(
    text: str,
    source_message_id: str = "",
    source_email: str = "",
    sender: str = "",
    attachment_name: str = "",
    source_type: str = "email_body",
    run_id: str = "",
    enable_ai: bool = True,
    llm_provider: Optional[LLMProvider] = None,
) -> list[ErrorRecord]:
    """
    Complete Hybrid Error Extraction (Stage 1 Deterministic + Stage 2 AI Enrichment).
    """
    records: list[ErrorRecord] = []
    source_info = f"{source_email} - {attachment_name or 'Body'}"

    # Stage 1: Deterministic regex extraction
    findings = extract_errors(text, source=source_info)
    for f in findings:
        records.append(
            ErrorRecord(
                raw_code=f.message,
                normalized_code=f.code,
                message=f.message,
                context=f.context,
                severity=SeverityLevel(f.severity if f.severity in SeverityLevel.__members__ else "MEDIUM"),
                source_message_id=source_message_id,
                source_email=source_email,
                sender=sender,
                attachment_name=attachment_name,
                source_type=source_type,
                occurrence_count=1,
                first_seen_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
                ai_confidence=f.confidence,
                run_id=run_id,
            )
        )

    # Stage 2: AI extraction for complex/unstructured context
    if enable_ai and text:
        try:
            ai = llm_provider or get_llm_provider()
            ai_results = ai.extract_structured_errors(text[:10000], source_context=source_info)
            for item in ai_results:
                raw_code = item.get("error_code", "")
                if not raw_code:
                    continue
                norm_code = normalize_code(raw_code)
                # Check if already extracted
                existing = next((r for r in records if r.normalized_code == norm_code), None)
                if existing:
                    # Enrich existing deterministic finding with AI detail
                    if item.get("message") and len(item["message"]) > len(existing.message):
                        existing.message = item["message"]
                    if item.get("context"):
                        existing.context = item["context"]
                    if item.get("severity"):
                        sev_str = item["severity"].upper()
                        if sev_str in SeverityLevel.__members__:
                            existing.severity = SeverityLevel(sev_str)
                    existing.ai_confidence = float(item.get("confidence", 0.9))
                else:
                    sev_str = (item.get("severity") or "MEDIUM").upper()
                    sev = SeverityLevel(sev_str) if sev_str in SeverityLevel.__members__ else SeverityLevel.MEDIUM
                    records.append(
                        ErrorRecord(
                            raw_code=raw_code,
                            normalized_code=norm_code,
                            message=item.get("message", raw_code),
                            context=item.get("context", ""),
                            severity=sev,
                            source_message_id=source_message_id,
                            source_email=source_email,
                            sender=sender,
                            attachment_name=attachment_name,
                            source_type=source_type,
                            occurrence_count=1,
                            first_seen_at=datetime.now(timezone.utc),
                            last_seen_at=datetime.now(timezone.utc),
                            ai_confidence=float(item.get("confidence", 0.85)),
                            run_id=run_id,
                        )
                    )
        except Exception as e:
            logger.warning(f"AI error extraction skipped or failed: {str(e)}")

    return records
