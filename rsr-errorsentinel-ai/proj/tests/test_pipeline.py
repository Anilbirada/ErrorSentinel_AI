import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.ai import MockLLMProvider
from app.pipeline import Pipeline
from tests.conftest import add_email

LOG1 = b"ERR-5021 Database connection timeout\nERR-7788 Payment gateway timeout\n"
LOG2 = LOG1 + b"ERR-9001 API authentication failure\n"


def att(data, name="production.log"):
    return [(name, "text/plain", data)]


def test_new_error_detection_and_alert(env):
    add_email(env.provider, attachments=att(LOG1))
    r = env.pipeline.run()
    assert r.new_codes == ["ERR-5021", "ERR-7788"]
    assert r.notification_status == "SENT" and r.registry_status == "COMMITTED"
    assert env.registry.all_codes() == ["ERR-5021", "ERR-7788"]
    assert "2 New Errors" in env.provider.outbox[0]["subject"]


def test_existing_error_detection_no_alert(env):
    env.registry.seed_from_file(_seed(env, "ERR-5021\nERR-7788\n"))
    add_email(env.provider, body="Error-5021 database timeout")
    r = env.pipeline.run()
    assert r.new_codes == [] and r.existing_codes == ["ERR-5021"] and env.provider.outbox == []


def _seed(env, text):
    p = env.settings.sqlite_path + ".seed.txt"
    open(p, "w").write(text)
    return p


def test_authority_is_registry_not_llm(env):
    """Even if the LLM claims a code is 'new', the registry lookup decides."""
    env.registry.seed_from_file(_seed(env, "ERR-5021\n"))
    llm = MockLLMProvider(lambda s, p: '{"errors":[{"error_code":"Err 5021","severity":"HIGH"}]}')
    pipe = Pipeline(env.settings, env.db, env.registry, env.provider, llm)
    add_email(env.provider, body="the nightly job failed: Err 5021 appeared again")
    assert pipe.run().new_codes == []


def test_duplicates_within_run_one_logical_error(env):
    add_email(env.provider, body="ERR-5021 one", attachments=att(b"ERR-5021 two\nerr-5021 three"))
    add_email(env.provider, body="Error 5021 four")
    r = env.pipeline.run()
    assert r.new_codes == ["ERR-5021"]
    with env.db.connection() as c:
        assert c.execute("SELECT occurrence_count FROM extracted_errors").fetchone()[0] == 4
        assert c.execute("SELECT COUNT(*) FROM error_registry").fetchone()[0] == 1
    assert len(env.provider.outbox) == 1


def test_same_error_across_attachments_and_emails(env):
    add_email(env.provider, attachments=att(LOG1, "a.log") + att(LOG1, "b.txt"))
    add_email(env.provider, attachments=att(LOG1, "c.log"))
    r = env.pipeline.run()
    assert r.new_codes == ["ERR-5021", "ERR-7788"]
    with env.db.connection() as c:
        assert c.execute("SELECT occurrence_count FROM error_registry WHERE normalized_code='ERR-5021'").fetchone()[0] == 3


def test_notification_failure_leaves_registry_unchanged_and_is_retryable(env):
    add_email(env.provider, attachments=att(LOG1))
    env.pipeline.run()
    add_email(env.provider, attachments=att(LOG2))
    env.provider.fail_sends = True
    r = env.pipeline.run()
    assert r.status == "notification_failed" and r.registry_status == "UNCHANGED"
    assert r.new_codes == ["ERR-9001"]
    assert env.registry.all_codes() == ["ERR-5021", "ERR-7788"]          # unchanged
    with env.db.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM pending_errors").fetchone()[0] == 3  # nothing lost
        assert c.execute("SELECT COUNT(*) FROM notification_attempts WHERE status='FAILED'").fetchone()[0] == 2

    env.provider.fail_sends = False                                      # retry, no new mail needed
    r2 = env.pipeline.run()
    assert r2.new_codes == ["ERR-9001"] and r2.registry_status == "COMMITTED"
    assert env.registry.all_codes() == ["ERR-5021", "ERR-7788", "ERR-9001"]
    r3 = env.pipeline.run()
    assert r3.new_codes == [] and len(env.provider.outbox) == 2          # no duplicate alert
    with env.db.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM pending_errors").fetchone()[0] == 0
        # occurrence of existing codes seen during the failed run is preserved, counted once
        assert c.execute("SELECT occurrence_count FROM error_registry WHERE normalized_code='ERR-5021'").fetchone()[0] == 2


def test_provider_exception_counts_as_failed_delivery(env):
    add_email(env.provider, body="ERR-1234 boom")
    env.provider.send_message = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down"))
    r = env.pipeline.run()
    assert r.notification_status == "FAILED" and env.registry.all_codes() == []


def test_registry_updated_after_success_only(env):
    add_email(env.provider, body="ERR-4321 x")
    assert env.registry.all_codes() == []
    env.pipeline.run()
    assert env.registry.all_codes() == ["ERR-4321"]


def test_registry_commit_is_atomic_and_idempotent(env):
    add_email(env.provider, body="ERR-1111 a\nERR-2222 b")
    env.registry._test_hook = lambda: (_ for _ in ()).throw(RuntimeError("disk full"))
    r = env.pipeline.run()                       # alert sent, but commit blows up -> rollback
    assert r.status == "failed" and env.registry.all_codes() == []
    env.registry._test_hook = None
    r2 = env.pipeline.run()                      # pending retried
    assert env.registry.all_codes() == ["ERR-1111", "ERR-2222"]
    from app.models import ErrorRecord  # same run_id commit twice must not double count
    with env.db.connection() as c:
        run_id = c.execute("SELECT run_id FROM registry_commits").fetchone()[0]
    recs = env.pipeline._load_pending()
    assert env.registry.commit(run_id, list(recs.values()) or []) == 0


def test_state_persistence_and_restart_recovery(env):
    add_email(env.provider, attachments=att(LOG1))
    env.pipeline.run()
    from app.database import Database
    from app.normalization import Normalizer
    from app.registry import Registry
    db2 = Database(env.settings.sqlite_path)                            # "restart"
    pipe2 = Pipeline(env.settings, db2, Registry(db2, Normalizer()), env.provider)
    r = pipe2.run()
    assert r.emails_processed == 0 and r.new_codes == []                # message not re-processed
    assert db2.get_state("last_successful_run") and db2.get_state("last_scan_timestamp")


def test_restart_recovers_pending_after_failed_alert(env):
    add_email(env.provider, body="ERR-8080 crash")
    env.provider.fail_sends = True
    env.pipeline.run()
    from app.database import Database
    from app.normalization import Normalizer
    from app.registry import Registry
    db2 = Database(env.settings.sqlite_path)
    env.provider.fail_sends = False
    r = Pipeline(env.settings, db2, Registry(db2, Normalizer()), env.provider).run()
    assert r.new_codes == ["ERR-8080"] and r.registry_status == "COMMITTED"


def test_corrupted_and_unsupported_attachments_are_reported_not_fatal(env):
    add_email(env.provider, body="ERR-6000 ok", attachments=[("bad.pdf", "x", b"junk"), ("a.exe", "x", b"MZ")])
    r = env.pipeline.run()
    assert r.new_codes == ["ERR-6000"] and len(r.failures) == 2
    assert "FAILED" in env.provider.outbox[0]["html"] or "UNSUPPORTED" in env.provider.outbox[0]["html"]


def test_ai_failure_does_not_break_pipeline(env):
    def boom(s, p): raise TimeoutError()
    pipe = Pipeline(env.settings, env.db, env.registry, env.provider, MockLLMProvider(boom))
    add_email(env.provider, body="ERR-1001 fine", attachments=att(b"weird failure no code here"))
    r = pipe.run()
    assert r.new_codes == ["ERR-1001"] and any("AI enrichment incomplete" in f for f in r.failures)


def test_provider_listing_failure_is_a_failed_run_with_no_state_change(env):
    env.provider.fail_listing = True
    r = env.pipeline.run()
    assert r.status == "failed" and env.db.get_state("last_scan_timestamp") is None


def test_report_separates_facts_from_ai(env):
    llm = MockLLMProvider(lambda s, p: '{"summary":"Possible DB issue","possible_causes":["pool exhausted"]}')
    pipe = Pipeline(env.settings, env.db, env.registry, env.provider, llm)
    add_email(env.provider, body="ERR-3003 <script>alert(1)</script>")
    pipe.run()
    html = env.provider.outbox[0]["html"]
    assert "Observed facts" in html and "AI interpretation" in html and "Not verified" in html
    assert "<script>" not in html                                       # output is escaped


def test_overlapping_runs_are_prevented(env):
    add_email(env.provider, body="ERR-5555 x")
    started, release = threading.Event(), threading.Event()
    env.provider.on_list = lambda: (started.set(), release.wait(5))
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(env.pipeline.run)
        assert started.wait(5)
        second = env.pipeline.run()
        release.set()
        assert first.result().status == "completed"
    assert second.status == "already_running" and second.run_id


def test_concurrent_attachment_processing_is_consistent(env):
    for i in range(12):
        add_email(env.provider, attachments=[(f"f{j}.log", "text/plain", f"ERR-{3000 + j} line {i}".encode())
                                             for j in range(6)])
    r = env.pipeline.run()
    assert len(r.new_codes) == 6 and r.emails_processed == 12
    with env.db.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM error_registry").fetchone()[0] == 6
        assert c.execute("SELECT occurrence_count FROM error_registry WHERE normalized_code='ERR-3000'").fetchone()[0] == 12
