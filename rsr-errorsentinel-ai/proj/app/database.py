"""SQLite access layer. Manual transactions (BEGIN IMMEDIATE) so commits are explicit and atomic."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_runs (
  run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
  emails_scanned INTEGER DEFAULT 0, emails_processed INTEGER DEFAULT 0,
  attachments_processed INTEGER DEFAULT 0, errors_extracted INTEGER DEFAULT 0,
  new_errors INTEGER DEFAULT 0, existing_errors INTEGER DEFAULT 0,
  notification_status TEXT, registry_status TEXT, failures INTEGER DEFAULT 0,
  metrics_json TEXT, report_path TEXT, error_message TEXT);
CREATE TABLE IF NOT EXISTS emails (
  message_id TEXT PRIMARY KEY, thread_id TEXT, sender TEXT, subject TEXT, received_at TEXT,
  provider TEXT, run_id TEXT REFERENCES monitoring_runs(run_id), status TEXT NOT NULL, processed_at TEXT);
CREATE TABLE IF NOT EXISTS attachments (
  attachment_id TEXT NOT NULL, message_id TEXT NOT NULL REFERENCES emails(message_id),
  filename TEXT, mime_type TEXT, size INTEGER, sha256 TEXT, local_path TEXT,
  processing_status TEXT, extracted_text TEXT, created_at TEXT,
  PRIMARY KEY (message_id, attachment_id));
CREATE TABLE IF NOT EXISTS extracted_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES monitoring_runs(run_id),
  raw_code TEXT, normalized_code TEXT NOT NULL, message TEXT, context TEXT, severity TEXT,
  source_message_id TEXT, source_email TEXT, attachment_name TEXT, source_type TEXT,
  occurrence_count INTEGER, first_seen_at TEXT, last_seen_at TEXT, ai_confidence REAL);
CREATE TABLE IF NOT EXISTS error_registry (
  id INTEGER PRIMARY KEY AUTOINCREMENT, normalized_code TEXT NOT NULL UNIQUE,
  first_seen_at TEXT, last_seen_at TEXT, occurrence_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'ACTIVE', source TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS pending_errors (
  normalized_code TEXT PRIMARY KEY, payload_json TEXT NOT NULL, run_id TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS notification_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, attempt INTEGER, status TEXT,
  provider_message_id TEXT, error_message TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS registry_commits (
  run_id TEXT PRIMARY KEY, committed_at TEXT, codes_added INTEGER);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, run_id TEXT, job_type TEXT, status TEXT, started_at TEXT,
  completed_at TEXT, retry_count INTEGER DEFAULT 0, error_message TEXT);
CREATE TABLE IF NOT EXISTS processing_state (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_registry_created ON error_registry(created_at);
CREATE INDEX IF NOT EXISTS idx_registry_status ON error_registry(status);
CREATE INDEX IF NOT EXISTS idx_errors_code ON extracted_errors(normalized_code);
CREATE INDEX IF NOT EXISTS idx_errors_run ON extracted_errors(run_id);
CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Autocommit connection for reads and single statements."""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """All-or-nothing write transaction."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # processing_state helpers -------------------------------------------------
    def get_state(self, key: str, default: str | None = None) -> str | None:
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM processing_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    @staticmethod
    def set_state_in(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute("INSERT INTO processing_state(key,value) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def set_state(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            self.set_state_in(conn, key, value)

    def processed_message_ids(self) -> set[str]:
        with self.connection() as conn:
            return {r["message_id"] for r in conn.execute(
                "SELECT message_id FROM emails WHERE status='PROCESSED'")}
