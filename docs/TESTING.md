# Automated Testing Strategy — RSR ErrorSentinel AI

## 1. Test Suite Overview

ErrorSentinel comes with a comprehensive test suite in `tests/` powered by `pytest` and `pytest-asyncio`.

All unit and integration tests use in-memory SQLite instances, mock email providers, and mock LLM engines so tests run completely offline without external dependencies or secrets.

---

## 2. Running Tests

```bash
# Run all tests
python -m pytest

# Run with verbose output
python -m pytest -v

# Run specific test requirement suite
python -m pytest tests/test_all_requirements.py
```

---

## 3. Coverage of 35 Business Specifications

- **Detection**: New vs Existing error code identification.
- **Normalization**: Unicode dash standardizing, whitespace trimming, prefix casing.
- **Deduplication**: Aggregate counts across multiple emails and attachments in a single run.
- **Document Extractors**: PDF, DOCX, XLSX, XLS, CSV, JSON, XML, TXT, LOG, corrupted files, unsupported files.
- **AI Engine**: Structured responses, malformed LLM fallbacks, timeout handling.
- **Mandatory Transaction Rule**: Unsent alerts leave master registry strictly unchanged; successful delivery commits atomic updates.
- **State & Concurrency**: Message deduplication state, persistent recovery, scheduler overlap mutex.
