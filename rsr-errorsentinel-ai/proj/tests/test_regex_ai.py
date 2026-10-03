import json

import pytest

from app.ai import AIAnalyzer, AIExtractor, LLMError, MockLLMProvider, parse_errors_response
from app.config import Settings
from app.extraction.errors import RegexErrorExtractor, rules_from_json
from app.normalization import Normalizer

S = Settings(llm_retries=1, notify_backoff_s=0.0)


def codes(text):
    n, x = Normalizer(), RegexErrorExtractor()
    return [n.normalize(f.canonical) for f in x.extract(text)]


def test_regex_extraction_variety():
    text = ("ERR-5021 Database connection timeout\nHTTP 503 upstream\nORA-12541: no listener\n"
            "SQLSTATE[08006] failed\njava.lang.NullPointerException at Foo\nConnection refused by host\n")
    assert codes(text) == ["ERR-5021", "HTTP-503", "ORA-12541", "SQLSTATE-08006",
                           "EXC-NULLPOINTEREXCEPTION", "MSG-CONNECTION-REFUSED"]


def test_log_timestamps_are_not_error_codes():
    assert codes("2026-10-03 ERROR 2026-10-03 something happened") == []


def test_phrase_rules_do_not_duplicate_coded_lines():
    assert codes("ERR-9001 API authentication failure") == ["ERR-9001"]


def test_custom_patterns(tmp_path):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps([{"name": "acme", "regex": r"ACME#(\d+)", "template": "ACME-{1}"}]))
    found = RegexErrorExtractor(rules_from_json(p)).extract("saw ACME#77 today")
    assert found[0].canonical == "ACME-77"


GOOD = json.dumps({"errors": [{"error_code": "Err 4404", "message": "m", "context": "c",
                               "severity": "HIGH", "confidence": 0.8}]})
TEXT = "the job failed with Err 4404 overnight"


def test_llm_structured_response():
    findings, status = AIExtractor(MockLLMProvider(lambda s, p: GOOD), S).extract(TEXT)
    assert status == "OK" and findings[0].severity == "HIGH" and findings[0].confidence == 0.8


def test_llm_invented_code_is_dropped():
    bad = json.dumps({"errors": [{"error_code": "ERR-9999"}]})
    findings, status = AIExtractor(MockLLMProvider(lambda s, p: bad), S).extract(TEXT)
    assert findings == [] and status == "OK"


def test_malformed_llm_response_is_safe():
    with pytest.raises(LLMError):
        parse_errors_response("not json")
    findings, status = AIExtractor(MockLLMProvider(lambda s, p: "oops"), S).extract(TEXT)
    assert findings == [] and status == "FAILED"


def test_llm_timeout_is_retried_then_reported():
    def boom(s, p): raise TimeoutError()
    llm = MockLLMProvider(boom)
    findings, status = AIExtractor(llm, S).extract(TEXT)
    assert status == "FAILED" and llm.calls == 2   # initial + 1 retry


def test_llm_not_called_without_error_hints():
    llm = MockLLMProvider(lambda s, p: GOOD)
    assert AIExtractor(llm, S).extract("all good, nothing to see")[1] == "SKIPPED" and llm.calls == 0


def test_analyzer_returns_none_on_failure():
    from datetime import datetime, timezone
    from app.models import ErrorRecord
    t = datetime.now(timezone.utc)
    r = ErrorRecord("x", "ERR-1", "m", "c", "LOW", "m1", "a", "", "email_body", t, t)
    assert AIAnalyzer(MockLLMProvider(lambda s, p: "bad"), S).analyze([r]) is None
