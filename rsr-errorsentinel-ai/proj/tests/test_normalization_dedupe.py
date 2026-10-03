from datetime import datetime, timezone

from app.dedupe import deduplicate
from app.models import ErrorRecord
from app.normalization import Normalizer

N = Normalizer()


def test_case_normalization():
    assert N.normalize("err-5021") == N.normalize("ERR-5021") == "ERR-5021"


def test_whitespace_prefix_and_unicode_dash_normalization():
    assert N.normalize("  Error-5021 ") == "ERR-5021"
    assert N.normalize("ERR\u20135021") == "ERR-5021"          # en dash
    assert N.normalize("ERR   5021") == "ERR-5021"
    assert N.normalize("http 404") == "HTTP-404"


def rec(code, msg_id="m1", att="", count=1, sev="MEDIUM"):
    t = datetime.now(timezone.utc)
    return ErrorRecord("raw", code, "msg", "ctx", sev, msg_id, "a@x", att, "attachment", t, t, count,
                       sources=[f"{msg_id}:{att or 'body'}"])


def test_duplicates_collapse_and_occurrences_sum():
    out = deduplicate([rec("ERR-1"), rec("ERR-1", "m2"), rec("ERR-1", "m3", "a.log", sev="HIGH")])
    assert list(out) == ["ERR-1"]
    assert out["ERR-1"].occurrence_count == 3
    assert out["ERR-1"].severity == "HIGH"
    assert len(out["ERR-1"].sources) == 3
