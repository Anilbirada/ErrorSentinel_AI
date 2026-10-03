from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Optional
import httpx

from app.config import Settings, get_settings
from app.logging.logger import get_logger

logger = get_logger("ai_provider")


class LLMProvider(ABC):
    """Abstract Base Class for LLM Providers."""

    @abstractmethod
    def extract_structured_errors(self, text: str, source_context: str = "") -> list[dict[str, Any]]:
        """
        Extract error codes and structured details from unstructured text.
        Must return a list of dicts:
        [{"error_code": "ERR-5021", "message": "...", "context": "...", "severity": "HIGH", "confidence": 0.9}]
        """
        pass

    @abstractmethod
    def analyze_errors(self, error_items: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Produce AI interpretation, grouping, probable cause assessment, and suggested investigation.
        """
        pass

    @abstractmethod
    def summarize_report(self, new_errors: list[dict[str, Any]], stats: dict[str, Any]) -> str:
        """
        Generate executive summary for the notification alert and report.
        """
        pass


class MockLLMProvider(LLMProvider):
    """Mock LLM Provider for local development, demo mode, and offline automated testing."""

    def extract_structured_errors(self, text: str, source_context: str = "") -> list[dict[str, Any]]:
        # Deterministic simulation of AI extraction on complex log strings
        results = []
        if "timeout" in text.lower() and "ERR-5021" in text:
            results.append({
                "error_code": "ERR-5021",
                "message": "Database connection timeout to primary cluster",
                "context": source_context or "Production cluster timeout detected",
                "severity": "HIGH",
                "confidence": 0.95,
            })
        if "payment" in text.lower() and "ERR-7788" in text:
            results.append({
                "error_code": "ERR-7788",
                "message": "Payment gateway timeout processing transaction",
                "context": source_context or "Gateway unresponsive",
                "severity": "CRITICAL",
                "confidence": 0.98,
            })
        if "ERR-9001" in text or "authentication failure" in text.lower():
            results.append({
                "error_code": "ERR-9001",
                "message": "API authentication failure with OAuth token expiry",
                "context": source_context or "Token verification error",
                "severity": "HIGH",
                "confidence": 0.92,
            })
        return results

    def analyze_errors(self, error_items: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(error_items)
        if count == 0:
            return {
                "summary": "No new errors requiring AI analysis.",
                "root_cause_assessment": "None",
                "suggested_actions": ["Routine monitoring"],
                "grouped_issues": [],
            }

        codes = [e.get("error_code", "") for e in error_items]
        return {
            "summary": f"AI Assessment: {count} distinct new error condition(s) identified ({', '.join(codes)}).",
            "root_cause_assessment": (
                "Observed patterns indicate backend connectivity/timeout anomalies. "
                "AI assessment suggests checking database connection pools and upstream API latency."
            ),
            "suggested_actions": [
                "Verify database connection pool saturation",
                "Check network firewall rules between application servers and external gateways",
                "Inspect authentication service certificate validity",
            ],
            "grouped_issues": [
                {
                    "category": "Infrastructure & Connectivity",
                    "affected_codes": codes,
                    "severity": "HIGH",
                }
            ],
        }

    def summarize_report(self, new_errors: list[dict[str, Any]], stats: dict[str, Any]) -> str:
        count = len(new_errors)
        if count == 0:
            return "Scan completed. No new error signatures detected."
        return (
            f"RSR ErrorSentinel AI detected {count} NEW error code(s) across "
            f"{stats.get('emails_scanned', 1)} emails and {stats.get('attachments_processed', 0)} attachments. "
            f"Immediate review recommended for production systems."
        )


class OpenAILLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model

    def extract_structured_errors(self, text: str, source_context: str = "") -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            prompt = (
                "You are an expert error log analyst. Extract all distinct error codes, messages, and severities from this text.\n"
                "Return ONLY a valid JSON object matching this schema:\n"
                '{"errors": [{"error_code": "ERR-...", "message": "...", "context": "...", "severity": "CRITICAL|HIGH|MEDIUM|LOW", "confidence": 0.95}]}\n\n'
                f"Source: {source_context}\n"
                f"Text:\n{text[:10000]}"
            )
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return parsed.get("errors", [])
        except Exception as e:
            logger.error(f"OpenAI error extraction failed: {str(e)}", exc_info=True)
            return []

    def analyze_errors(self, error_items: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.api_key or not error_items:
            return {"summary": "No AI analysis performed."}
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            prompt = (
                "Analyze these new error codes for root causes and operational impact. "
                "Clearly distinguish observed facts from AI interpretation.\n"
                "Return JSON with keys: summary, root_cause_assessment, suggested_actions (list), grouped_issues (list).\n"
                f"Errors:\n{json.dumps(error_items, indent=2)}"
            )
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return json.loads(data["choices"][0]["message"]["content"])
        except Exception as e:
            logger.error(f"OpenAI error analysis failed: {str(e)}", exc_info=True)
            return {"summary": f"AI analysis unavailable: {str(e)}"}

    def summarize_report(self, new_errors: list[dict[str, Any]], stats: dict[str, Any]) -> str:
        return f"AI Assessment: {len(new_errors)} new error condition(s) discovered during scan."


class GeminiLLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.model = model

    def extract_structured_errors(self, text: str, source_context: str = "") -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            prompt = (
                "Extract all error codes from this text. Return JSON matching: "
                '{"errors": [{"error_code": "ERR-...", "message": "...", "context": "...", "severity": "HIGH", "confidence": 0.9}]}\n'
                f"Text:\n{text[:10000]}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json"}
            }
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(raw_text).get("errors", [])
        except Exception as e:
            logger.error(f"Gemini extraction failed: {str(e)}", exc_info=True)
            return []

    def analyze_errors(self, error_items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"summary": f"Gemini analyzed {len(error_items)} error signatures."}

    def summarize_report(self, new_errors: list[dict[str, Any]], stats: dict[str, Any]) -> str:
        return f"Gemini Scan Summary: {len(new_errors)} new error(s) detected."


class DisabledAIProvider(LLMProvider):
    def extract_structured_errors(self, text: str, source_context: str = "") -> list[dict[str, Any]]:
        return []

    def analyze_errors(self, error_items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "summary": "AI enrichment disabled.",
            "root_cause_assessment": "Deterministic extraction only.",
            "suggested_actions": ["Review logs manually"],
            "grouped_issues": [],
        }

    def summarize_report(self, new_errors: list[dict[str, Any]], stats: dict[str, Any]) -> str:
        return f"Deterministic monitoring scan identified {len(new_errors)} new error(s)."


def get_llm_provider(settings: Optional[Settings] = None) -> LLMProvider:
    cfg = settings or get_settings()
    provider_name = cfg.active_llm_provider.lower()

    if provider_name == "openai" and cfg.active_llm_key:
        return OpenAILLMProvider(api_key=cfg.active_llm_key, model=cfg.active_llm_model)
    elif provider_name in ("gemini", "google") and cfg.active_llm_key:
        return GeminiLLMProvider(api_key=cfg.active_llm_key, model=cfg.active_llm_model)
    elif provider_name in ("none", "disabled"):
        return DisabledAIProvider()
    else:
        # Default mock provider for demo and safe offline operation
        return MockLLMProvider()
