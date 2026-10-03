"""LLM abstraction. The LLM extracts/summarizes only; it never decides NEW vs EXISTING."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Literal

from pydantic import BaseModel, ValidationError

from .config import Settings
from .models import RawFinding

log = logging.getLogger("sentinel.ai")
HINT = re.compile(r"\b(error|exception|fail(?:ed|ure|ing)?|fatal|critical|timeout|refused|denied|crash(?:ed)?)\b", re.I)

EXTRACT_SYSTEM = (
    "You extract error codes from logs and emails. Reply with ONLY JSON: "
    '{"errors":[{"error_code":str,"message":str,"context":str,"severity":"LOW|MEDIUM|HIGH|CRITICAL","confidence":0-1}]}. '
    "Only report codes that appear literally in the text. Never invent codes, causes or sources.")
ANALYZE_SYSTEM = (
    "You assist an operations team. Reply with ONLY JSON: "
    '{"summary":str,"groups":[str],"possible_causes":[str],"investigation_areas":[str]}. '
    "Use cautious wording (possible, may). Do not state causes as facts.")


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    available = True

    @abstractmethod
    def complete(self, system: str, prompt: str, timeout: float) -> str: ...


class NullLLMProvider(LLMProvider):
    available = False

    def complete(self, system: str, prompt: str, timeout: float) -> str:
        raise LLMError("no LLM configured")


class MockLLMProvider(LLMProvider):
    """Test/demo provider. `responder` may return text or raise."""

    def __init__(self, responder: Callable[[str, str], str]) -> None:
        self.responder = responder
        self.calls = 0

    def complete(self, system: str, prompt: str, timeout: float) -> str:
        self.calls += 1
        return self.responder(system, prompt)


class AnthropicProvider(LLMProvider):
    """Thin adapter over the official SDK. NOTE: not exercised by tests (needs a real API key)."""

    def __init__(self, api_key: str, model: str) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, prompt: str, timeout: float) -> str:
        try:
            msg = self._client.messages.create(model=self._model, max_tokens=1500, system=system,
                                               messages=[{"role": "user", "content": prompt}], timeout=timeout)
        except Exception as exc:
            raise LLMError(type(exc).__name__) from exc
        return "".join(b.text for b in msg.content if getattr(b, "text", None))


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings.llm_api_key, settings.llm_model)
    return NullLLMProvider()


class AIErrorItem(BaseModel):
    error_code: str
    message: str = ""
    context: str = ""
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    confidence: float | None = None


class AIErrorResponse(BaseModel):
    errors: list[AIErrorItem]


class AIAnalysis(BaseModel):
    summary: str
    groups: list[str] = []
    possible_causes: list[str] = []
    investigation_areas: list[str] = []


def _json_from(text: str) -> object:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    return json.loads(t)


def parse_errors_response(text: str) -> AIErrorResponse:
    try:
        return AIErrorResponse.model_validate(_json_from(text))
    except (ValueError, ValidationError) as exc:
        raise LLMError("malformed LLM response") from exc


def _compact(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _excerpt(text: str, limit: int) -> str:
    lines = text.splitlines()
    keep: list[str] = []
    for i, line in enumerate(lines):
        if HINT.search(line):
            keep.extend(lines[max(0, i - 1): i + 2])
    out = "\n".join(dict.fromkeys(keep))
    return out[:limit]


class _Retrying:
    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm, self.s = llm, settings
        self.sem = threading.BoundedSemaphore(settings.max_llm_concurrency)

    def call(self, system: str, prompt: str) -> str:
        last: Exception | None = None
        for attempt in range(self.s.llm_retries + 1):
            try:
                with self.sem:
                    return self.llm.complete(system, prompt, self.s.llm_timeout_s)
            except Exception as exc:   # timeouts, API errors, anything: never crash the pipeline
                last = exc
                log.warning("LLM call failed (attempt %d): %s", attempt + 1, type(exc).__name__)
                if attempt < self.s.llm_retries:
                    time.sleep(min(self.s.notify_backoff_s, 2.0) * (2 ** attempt) * 0.5)
        raise LLMError(type(last).__name__ if last else "unknown")


class AIExtractor:
    """Stage 2: only called when regex found nothing but the text looks error-like."""

    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm, self.s, self._r = llm, settings, _Retrying(llm, settings)

    def extract(self, text: str) -> tuple[list[RawFinding], str]:
        """Returns (findings, status) where status is OK | SKIPPED | FAILED."""
        if not self.llm.available or not HINT.search(text):
            return [], "SKIPPED"
        excerpt = _excerpt(text, self.s.llm_max_chars)
        try:
            parsed = parse_errors_response(self._r.call(EXTRACT_SYSTEM, excerpt))
        except LLMError as exc:
            log.warning("AI extraction incomplete: %s", exc)
            return [], "FAILED"
        haystack = _compact(text)
        findings = []
        for item in parsed.errors:
            code = _compact(item.error_code)
            if not code or code not in haystack:     # provenance guard: no invented codes
                log.warning("dropped AI item not present in source text")
                continue
            findings.append(RawFinding(item.error_code, item.error_code, item.message, item.context,
                                       item.severity, item.confidence, rule="ai"))
        return findings, "OK"


class AIAnalyzer:
    """Interprets NEW errors for the report. Output is labelled AI assessment, never fact."""

    def __init__(self, llm: LLMProvider, settings: Settings) -> None:
        self.llm, self._r = llm, _Retrying(llm, settings)

    def analyze(self, records: list) -> AIAnalysis | None:
        if not self.llm.available or not records:
            return None
        listing = "\n".join(f"{r.normalized_code} [{r.severity}] x{r.occurrence_count}: {r.message}"
                            for r in records[:50])
        try:
            return AIAnalysis.model_validate(_json_from(self._r.call(ANALYZE_SYSTEM, listing)))
        except (LLMError, ValueError, ValidationError) as exc:
            log.warning("AI analysis unavailable: %s", type(exc).__name__)
            return None
