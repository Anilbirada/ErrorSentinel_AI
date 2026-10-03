# Performance & Latency Telemetry — RSR ErrorSentinel AI

## 1. Concurrency Model

ErrorSentinel separates async I/O from blocking operations:
- **FastAPI Core**: Async I/O for instant non-blocking request acknowledgments.
- **Background Worker Pool**: Dedicated `ThreadPoolExecutor` with bounded worker limits to prevent CPU and memory saturation.
  - `MAX_EMAIL_WORKERS` (Default: 5)
  - `MAX_ATTACHMENT_WORKERS` (Default: 5)
  - `MAX_LLM_CONCURRENCY` (Default: 3)

---

## 2. Telemetry Breakdown

Every monitoring run records millisecond-precision timings:
- `gmail_fetch_ms`: Time taken to list & fetch message metadata from provider.
- `message_processing_ms`: Body text parsing and cleaning.
- `attachment_download_ms`: File download and SHA-256 verification.
- `document_extraction_ms`: PDF, DOCX, XLSX text extraction.
- `regex_extraction_ms`: Deterministic regex scanning.
- `llm_analysis_ms`: AI root-cause and summarization latency.
- `registry_lookup_ms`: SQLite database deterministic comparison.
- `report_generation_ms`: HTML and JSON file rendering.
- `notification_ms`: Alert delivery network roundtrip.
- `total_run_ms`: Total execution time.

These metrics are accessible via `GET /api/metrics` and visualized on the operational dashboard.
