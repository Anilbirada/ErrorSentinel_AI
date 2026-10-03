# RSR ErrorSentinel AI  (stages 1-3)

Detect. Understand. Verify. Alert.

Monitors an inbox, extracts error codes from email bodies and attachments, and alerts only on
codes that are **not already in the master registry**.

## Golden rules (enforced in code and tests)
1. The LLM only extracts / summarizes. `Registry.known_codes()` (SQLite lookup) decides NEW vs EXISTING.
   AI-suggested codes must literally appear in the source text or they are dropped.
2. The registry changes **only after the provider accepts the alert**. On failure the new errors stay in
   `pending_errors` and are merged into the next run. Commit is one transaction, idempotent per `run_id`.

## What works now (tested)
- Normalization, in-run deduplication, SQLite registry with atomic commit, pending/retry, persisted state
- Extractors: PDF, DOCX, XLSX, XLS, CSV, JSON, XML (defusedxml), TXT, LOG, MD; size limit, corrupt-file handling,
  zip-bomb guard, safe filenames; identical attachments (SHA-256) are extracted once per run
- Configurable regex rules (`PATTERNS_FILE`), LLM abstraction with validation, retries, provenance guard
- HTML + JSON report (facts and AI interpretation separated, HTML-escaped), alert with retries
- Bounded thread pools, overlap prevention, per-stage timing metrics, job records, rotating redacted logs
- Offline demo, CLI, 53 pytest tests (no credentials needed)

## Not built yet (next stages)
Gmail provider (OAuth), Microsoft Graph provider, FastAPI + dashboard, APScheduler, Dockerfile, docs/.
`--run-now` and `--test-email` therefore print a clear "not implemented" message for gmail.
The Anthropic LLM adapter exists but has never been run against the real API.

## Run
```
pip install -r requirements.txt
python main.py --demo          # offline walkthrough of the 5 required scenarios
python -m pytest               # all tests
python main.py --check-config  # after copying .env.example to .env
```

## Design notes
- Attachments are processed in memory (never written to disk or executed), so no temp-file cleanup is needed.
- Delivery semantics: "success" = provider accepted the message. If the process dies after sending but before
  the registry commit, the next run re-sends (at-least-once alert); the registry never gets duplicates.
- Time filter: `list_messages(after=last_scan - SCAN_OVERLAP)` plus the processed-ID table, so opening an
  email manually never matters.
- Custom regex rules (`PATTERNS_FILE`): `[{"name":"acme","regex":"ACME#(\\d+)","template":"ACME-{1}"}]`
- Providers must be thread-safe or create per-thread clients (relevant for Gmail's HTTP client).
