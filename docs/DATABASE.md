# Database Schema & Registry Reference — RSR ErrorSentinel AI

## 1. Overview

ErrorSentinel uses SQLAlchemy with SQLite by default (`data/app.db`), designed for straightforward migration to PostgreSQL.

---

## 2. Core Tables

### `error_registry` (Master Registry)
- `id` (Integer, Primary Key)
- `code` (String, Unique, Index) — Normalized error code
- `first_seen_at` (DateTime)
- `last_seen_at` (DateTime)
- `occurrence_count` (Integer)
- `status` (String: ACTIVE, ARCHIVED, MUTED)
- `source` (String)
- `source_run_id` (String)

### `monitoring_runs` (Execution History)
- `id` (String, Primary Key) — Run ID
- `status` (String: PENDING, RUNNING, SUCCESS, FAILED)
- `started_at`, `completed_at` (DateTime)
- `duration_ms` (Float)
- `emails_scanned`, `emails_processed`, `attachments_processed`
- `new_codes`, `known_codes`, `failures`
- `notification_status`, `registry_status`

### `email_records` (Deduplication & Message State)
- `id` (String, Primary Key) — Message ID
- `thread_id` (String)
- `sender`, `subject`, `received_at`, `processed_at`
- `processing_status` (String: PROCESSED, SUCCESS, FAILED)

### `attachment_records` (Attachment Tracking)
- `id` (String, Primary Key)
- `message_id` (Foreign Key -> `email_records.id`)
- `filename`, `mime_type`, `size`, `hash` (SHA-256)
- `download_status`, `extraction_status`

### `extracted_errors` (Audit Trail)
- `id` (String, Primary Key)
- `run_id` (Foreign Key -> `monitoring_runs.id`)
- `raw_code`, `code` (normalized)
- `message`, `context`, `severity`, `confidence`
- `occurrence_count`, `is_new`

### `alert_deliveries` (Audit Log of Notifications)
- `id` (String, Primary Key)
- `run_id` (Foreign Key -> `monitoring_runs.id`)
- `recipient`, `subject`, `status` (SUCCESS/FAILED), `sent_at`, `error`
