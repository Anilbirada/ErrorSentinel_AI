# System Architecture — RSR ErrorSentinel AI

**Tagline:** Detect. Understand. Verify. Alert.

## 1. Executive Summary

RSR ErrorSentinel AI is an intelligent, high-reliability email error intelligence and monitoring agent. It continuously monitors configured mailboxes, ingests inbound error alerts, downloads and parses heterogeneous document attachments (PDF, DOCX, XLSX, XLS, CSV, JSON, XML, TXT, LOG), extracts discrete error signatures using a hybrid deterministic-AI extraction pipeline, normalizes codes, deduplicates occurrences, deterministically evaluates new vs. existing codes against a master database registry, and generates executive reports with automated alert notifications.

---

## 2. Core Architecture Pipeline

```
                 EMAIL PROVIDERS
          ┌─────────────┴─────────────┐
          │                           │
       Gmail API                 Microsoft Graph
      (Phase 1 Dev)              (Phase 2 Future)
          │                           │
          └─────────────┬─────────────┘
                        ↓
                COMMON EMAIL MODEL (EmailMessage)
                        ↓
                  EMAIL MONITOR & STATE (StateManager)
                        ↓
              ATTACHMENT PROCESSOR (Security & Sanitization)
                        ↓
                TEXT EXTRACTION (PyMuPDF, docx, pandas, etc.)
                        ↓
               ERROR EXTRACTION ENGINE
                  ┌─────┴─────┐
                  │           │
               REGEX          AI (LLMProvider)
                  └─────┬─────┘
                        ↓
               NORMALIZATION ENGINE (Unicode, dashes, prefixes)
                        ↓
               DEDUPLICATION ENGINE (Occurrence aggregation)
                        ↓
                MASTER REGISTRY (SQLite / PostgreSQL)
                        ↓
                DETERMINISTIC NEW / EXISTING DECISION
                        ↓
              AI ROOT-CAUSE ANALYSIS (Only for NEW errors)
                        ↓
                REPORT ENGINE (HTML & JSON)
                        ↓
             EMAIL NOTIFICATION (via EmailProvider)
                        ↓
             DELIVERY CONFIRMATION (HTTP Status / Send Response)
                        ↓
                 REGISTRY COMMIT (MANDATORY TRANSACTION RULE)
                        ↓
                AUDIT LOGGING & STATE ADVANCEMENT
                        ↓
                   SCHEDULER (APScheduler)
```

---

## 3. The Most Important Business Rule

> **THE LLM MUST NEVER BE THE AUTHORITY FOR NEW VS EXISTING.**

1. **LLM Responsibility**:
   - Extraction of complex error messages and context.
   - Severity classification recommendation.
   - Root-cause assessment and investigation suggestions.
   - Executive report summarization.

2. **Python + Database Responsibility**:
   - Error code normalization.
   - Deduplication and occurrence aggregation.
   - Master registry lookup (`RegistryDecision.NEW` vs `RegistryDecision.EXISTING`).
   - Transactional commit execution.

---

## 4. Mandatory Transaction Rule

> **NEVER update the master error registry before successful notification delivery.**

```
EMAIL INBOX
    ↓
EXTRACT ERRORS
    ↓
NORMALIZE & DEDUPLICATE
    ↓
CHECK MASTER REGISTRY
    ↓
NEW ERRORS DETECTED
    ↓
GENERATE REPORT
    ↓
SEND ALERT VIA EMAIL PROVIDER
    ↓
SUCCESSFUL DELIVERY CONFIRMED?
    ├── YES ──> ATOMIC REGISTRY COMMIT & SYNC
    └── NO  ──> DO NOT UPDATE REGISTRY (Errors remain retryable)
```

If email delivery fails:
- Master registry remains unchanged.
- Extracted error state remains uncommitted and retryable.
- Audit table records failed delivery attempt.
- Next cycle safely reprocesses without creating duplicates or missing notifications.

---

## 5. Modular Component Structure

- **`app/providers/`**: Base abstraction with `GmailProvider`, `MicrosoftGraphProvider`, and `DemoEmailProvider`.
- **`app/attachments/`**: Security validators, path traversal protection, SHA-256 deduplication hashing, and downloader.
- **`app/extraction/`**: PyMuPDF, python-docx, pandas/openpyxl, CSV, XML, JSON, and multi-encoding text extractors.
- **`app/errors/`**: Configurable regex patterns, Unicode normalizer, single-run deduplicator, and hybrid extractor.
- **`app/ai/`**: Abstract `LLMProvider` supporting OpenAI, Gemini, Anthropic, Ollama, and Mock modes.
- **`app/registry/`**: SQLite-backed ACID registry repository with synchronization to `data/existing_error_codes.txt`.
- **`app/reporting/`**: HTML & JSON report generators with strict separation between observed facts and AI interpretations.
- **`app/notifications/`**: Notification dispatcher enforcing the delivery-first transaction contract.
- **`app/jobs/`**: Background thread-pool worker manager with Server-Sent Events (SSE) live stream.
- **`app/scheduler/`**: APScheduler with overlap prevention mutex.
- **`app/api/`**: REST API endpoints for management, metrics, status, and manual triggering.
- **`dashboard/`**: Responsive real-time operational dashboard with all 13 core monitoring sections.
