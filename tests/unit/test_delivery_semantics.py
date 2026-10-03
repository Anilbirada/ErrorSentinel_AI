from app.errors.extractor import extract_errors
from app.errors.deduplicator import deduplicate
from app.registry.txt_registry import TxtRegistry

def test_unsent_new_code_is_not_registered(tmp_path):
    registry=TxtRegistry(tmp_path / "codes.txt")
    candidate=set(deduplicate(extract_errors("ERR-9001", "email:1")))
    # Notification failure: intentionally no add_codes call.
    assert candidate == {"ERR-9001"}
    assert not registry.exists("ERR-9001")

def test_sent_code_becomes_known(tmp_path):
    registry=TxtRegistry(tmp_path / "codes.txt")
    registry.add_codes({"ERR-9001"})
    assert registry.exists("err-9001")
