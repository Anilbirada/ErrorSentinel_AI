# RSR ErrorSentinel AI — Email Error Intelligence & Monitoring Agent

**Tagline:** Detect. Understand. Verify. Alert.

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite / PostgreSQL](https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-4479A1.svg)](https://www.sqlalchemy.org/)
[![Tests](https://img.shields.io/badge/Tests-33%20Passed-brightgreen.svg)]()

---

## 📖 What ErrorSentinel Does

**RSR ErrorSentinel AI** is an enterprise-grade autonomous monitoring agent that ingests inbound technical emails and incident alerts, extracts error signatures from attachments (PDF, DOCX, XLSX, XLS, CSV, JSON, XML, TXT, LOG), performs hybrid deterministic-AI extraction, normalizes and deduplicates findings, determines **genuinely NEW** error codes against a master database registry, generates HTML & JSON reports, sends automated alerts, and transactionally updates the registry **only after verified alert delivery**.

---

## 🛡️ The Most Important Business Rule

> **THE LLM MUST NOT BE THE AUTHORITY FOR NEW VS EXISTING.**

- **AI/LLM** = Understand, extract unstructured context, classify severity, assess probable cause.
- **Python + Database** = Normalize, deduplicate, perform deterministic lookups, maintain master registry, enforce ACID transaction rules.

---

## 🔒 Mandatory Transaction Rule

> **NEVER update the master error registry before successful notification delivery.**

1. `EXTRACT` -> `NORMALIZE` -> `DEDUPLICATE` -> `CHECK REGISTRY`
2. If new error codes exist: `GENERATE REPORT` -> `SEND ALERT`
3. **If delivery succeeds** -> Commit new codes to SQLite/PostgreSQL registry and sync text registry.
4. **If delivery fails** -> Do NOT update the registry. Unsent errors remain retryable in the next cycle.

---

## 🏗️ Architecture

```
                 EMAIL PROVIDERS
          ┌─────────────┴─────────────┐
          │                           │
       Gmail API                 Microsoft Graph
     (Phase 1 Dev)               (Phase 2 Future)
          │                           │
          └─────────────┬─────────────┘
                        ↓
                COMMON EMAIL MODEL (EmailMessage)
                        ↓
                  EMAIL MONITOR & PERSISTENT STATE
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

## ⚡ Quickstart

### 1. Installation
```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Interactive Demo Mode (No External Credentials Required)
```bash
python main.py --demo
```
This runs an end-to-end verification of new error detection, deduplication on rerun, transaction rollback on notification failure, and successful registry commitment on delivery.

### 3. Check Configuration Status
```bash
python main.py --check-config
```

### 4. Launch Web Dashboard & Background Scheduler
```bash
python main.py
```
- **Web Dashboard**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive REST API Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 💻 CLI Commands

| Command | Description |
|---|---|
| `python main.py` | Start web dashboard, REST API, and APScheduler background worker |
| `python main.py --run-now` | Trigger a single monitoring cycle immediately |
| `python main.py --demo` | Run full standalone end-to-end demo mode |
| `python main.py --check-config` | Preflight verification of Gmail, Graph, and AI configuration |
| `python main.py --status` | Display error counts, registered codes, and system status |
| `python main.py --test-email` | Send a test notification email through configured provider |

---

## 📊 Operational Dashboard

The ErrorSentinel web dashboard provides live visibility into:
1. **Overview & Counters**: Processed emails, new error counts, registered codes, alerts sent.
2. **Live Agent Monitor**: Real-time activity stream via Server-Sent Events (SSE).
3. **Error Registry**: Filterable table comparing NEW vs. EXISTING codes with occurrence counts.
4. **Execution History**: Audit trail of every monitoring run with duration and delivery status.
5. **Telemetry & Performance**: Latency metrics for fetching, extraction, AI analysis, and delivery.
6. **Gmail Connections**: Google sign-in, multiple independently monitored Gmail accounts, per-account health and run counters, reconnect, and disconnect.

Dashboard sign-in and mailbox OAuth require the Web OAuth client, callback URLs, stable session key, and token-encryption key documented in [Gmail API & OAuth Setup](docs/GMAIL_SETUP.md). The dashboard redirects to Google sign-in when no authenticated session exists. Legacy CLI OAuth remains separate.

---

## 🧪 Automated Testing

Run the comprehensive pytest suite covering all 35 business specifications:
```bash
python -m pytest -v
```

---

## 📚 Documentation Index

- [Architecture Guide](docs/ARCHITECTURE.md)
- [Installation Guide](docs/INSTALLATION.md)
- [Gmail API & OAuth Setup](docs/GMAIL_SETUP.md)
- [Configuration Reference](docs/CONFIGURATION.md)
- [AI & LLM Configuration](docs/AI_CONFIGURATION.md)
- [Database Schema & Registry](docs/DATABASE.md)
- [Error Extraction & Normalization](docs/ERROR_EXTRACTION.md)
- [Security Architecture](docs/SECURITY.md)
- [Automated Testing Strategy](docs/TESTING.md)
- [Production Deployment & Docker](docs/DEPLOYMENT.md)
- [Microsoft Graph Migration Path](docs/MICROSOFT_GRAPH_FUTURE.md)
- [Performance & Latency Telemetry](docs/PERFORMANCE.md)
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md)

---

## 📄 License
Enterprise Proprietary — RSR ErrorSentinel AI Team.
