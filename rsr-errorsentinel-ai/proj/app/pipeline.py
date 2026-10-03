"""Orchestrates one monitoring run.

Safety model: extracted NEW errors are persisted in `pending_errors` together with marking the
emails processed (one transaction). The registry is only touched by Registry.commit(), which is
called ONLY after the alert was accepted by the provider. A failed alert leaves the registry
unchanged and the pending errors are retried (merged into) the next run.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterator

from .ai import AIAnalyzer, AIExtractor, LLMProvider, NullLLMProvider
from .config import Settings
from .database import Database
from .dedupe import deduplicate
from .extraction.documents import DocumentExtractor
from .extraction.errors import RegexErrorExtractor
from .models import (EmailMessage, ErrorRecord, ExtractedDocument, RawFinding, RunResult, iso, utcnow)
from .normalization import Normalizer
from .notifier import Notifier
from .providers.base import EmailProvider
from .registry import Registry
from .reporting import build_report, render_html, write_reports

log = logging.getLogger("sentinel.pipeline")


class Metrics:
    def __init__(self) -> None:
        self._d: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, name: str, ms: float) -> None:
        with self._lock:
            self._d[name] = self._d.get(name, 0.0) + ms

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        t = time.perf_counter()
        try:
            yield
        finally:
            self.add(name, (time.perf_counter() - t) * 1000)

    def snapshot(self) -> dict[str, float]:
        return {k: round(v, 2) for k, v in self._d.items()}


@dataclass
class MessageWork:
    msg: EmailMessage
    attachments: list[dict] = field(default_factory=list)
    records: list[ErrorRecord] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _html_to_text(h: str) -> str:
    return re.sub(r"<[^>]+>", " ", h)


class Pipeline:
    def __init__(self, settings: Settings, db: Database, registry: Registry, provider: EmailProvider,
                 llm: LLMProvider | None = None, normalizer: Normalizer | None = None,
                 regex: RegexErrorExtractor | None = None) -> None:
        self.s, self.db, self.registry, self.provider = settings, db, registry, provider
        self.llm = llm or NullLLMProvider()
        self.normalizer = normalizer or registry.normalizer
        self.regex = regex or RegexErrorExtractor()
        self.docs = DocumentExtractor(settings.max_attachment_bytes)
        self.ai = AIExtractor(self.llm, settings)
        self.analyzer = AIAnalyzer(self.llm, settings)
        self.notifier = Notifier(provider, db, settings.alert_recipients,
                                 settings.notify_retries, settings.notify_backoff_s)
        self._run_lock = threading.Lock()
        self._active_run_id = ""
        self._extract_slots = threading.BoundedSemaphore(settings.max_attachment_workers)

    # public -----------------------------------------------------------------
    def run(self) -> RunResult:
        if not self._run_lock.acquire(blocking=False):
            return RunResult(run_id=self._active_run_id, status="already_running")
        try:
            return self._run()
        finally:
            self._run_lock.release()

    # internals --------------------------------------------------------------
    @contextmanager
    def _job(self, run_id: str, job_type: str) -> Iterator[None]:
        job_id, start = f"{run_id}:{job_type}", iso(utcnow())
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO jobs(job_id,run_id,job_type,status,started_at) VALUES(?,?,?,?,?)",
                      (job_id, run_id, job_type, "RUNNING", start))
        status, err = "SUCCESS", ""
        try:
            yield
        except BaseException as exc:
            status, err = "FAILED", type(exc).__name__
            raise
        finally:
            with self.db.transaction() as c:
                c.execute("UPDATE jobs SET status=?, completed_at=?, error_message=? WHERE job_id=?",
                          (status, iso(utcnow()), err, job_id))

    def _run(self) -> RunResult:
        started = utcnow()
        run_id = f"run_{started:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:4]}"
        self._active_run_id = run_id
        metrics, t0 = Metrics(), time.perf_counter()
        result = RunResult(run_id=run_id, status="completed")
        with self.db.transaction() as c:
            c.execute("INSERT INTO monitoring_runs(run_id, started_at, status) VALUES(?,?, 'RUNNING')",
                      (run_id, iso(started)))
        log.info("run started %s", run_id)
        try:
            self._execute(run_id, started, result, metrics)
        except Exception as exc:
            log.exception("run %s failed", run_id)
            result.status = "failed"
            result.failures.append(f"run aborted: {type(exc).__name__}")
        metrics.add("total_run_ms", (time.perf_counter() - t0) * 1000)
        result.metrics = metrics.snapshot()
        with self.db.transaction() as c:
            c.execute(
                "UPDATE monitoring_runs SET completed_at=?, status=?, emails_scanned=?, emails_processed=?, "
                "attachments_processed=?, errors_extracted=?, new_errors=?, existing_errors=?, "
                "notification_status=?, registry_status=?, failures=?, metrics_json=?, report_path=? WHERE run_id=?",
                (iso(utcnow()), result.status, result.emails_scanned, result.emails_processed,
                 result.attachments_processed, result.errors_extracted, len(result.new_codes),
                 len(result.existing_codes), result.notification_status, result.registry_status,
                 len(result.failures), json.dumps(result.metrics), result.report_path, run_id))
        log.info("run finished %s status=%s new=%d", run_id, result.status, len(result.new_codes))
        return result

    def _execute(self, run_id: str, started, result: RunResult, metrics: Metrics) -> None:
        # 1. scan ------------------------------------------------------------
        with self._job(run_id, "EMAIL_SCAN"), metrics.timer("gmail_fetch_ms"):
            last = self.db.get_state("last_scan_timestamp")
            after = None
            if last:
                from datetime import datetime
                after = datetime.fromisoformat(last) - timedelta(minutes=self.s.scan_overlap_minutes)
            listed = list(self.provider.list_messages(after))
            done = self.db.processed_message_ids()
            fresh = [m for m in listed if m.message_id not in done]
        result.emails_scanned = len(listed)

        # 2-4. attachments + extraction, bounded concurrency -------------------
        cache: dict[str, tuple[ExtractedDocument, list[RawFinding], str]] = {}
        lock = threading.Lock()
        with self._job(run_id, "DOCUMENT_EXTRACTION"):
            with ThreadPoolExecutor(max_workers=self.s.max_email_workers) as pool:
                futures = [(m, pool.submit(self._prepare, m, run_id, metrics, cache, lock)) for m in fresh]
            works: list[MessageWork] = []
            for m, fut in futures:
                try:
                    works.append(fut.result())
                except Exception as exc:     # message stays unprocessed and is retried next run
                    result.failures.append(f"{m.message_id}: {type(exc).__name__}")
        for w in works:
            result.failures.extend(w.failures)
            result.attachments_processed += sum(1 for a in w.attachments if a["status"] == "SUCCESS")
        result.emails_processed = len(works)

        # 5. normalize / dedupe / merge pending / registry decision -------------
        with self._job(run_id, "ERROR_ANALYSIS"), metrics.timer("registry_lookup_ms"):
            current = deduplicate(r for w in works for r in w.records)
            result.errors_extracted = sum(r.occurrence_count for r in current.values())
            pending = self._load_pending()
            merged = deduplicate(list(pending.values()) + list(current.values()))
            known = self.registry.known_codes(merged.keys())
            new = {c: r for c, r in merged.items() if c not in known}
            existing = {c: r for c, r in merged.items() if c in known}
        result.new_codes, result.existing_codes = sorted(new), sorted(existing)

        # persist processed state + pending (atomic) -------------------------
        self._persist(run_id, started, works, current, merged)

        # 6. report, notify, commit ------------------------------------------
        if not new:
            if existing:
                with self._job(run_id, "REGISTRY_COMMIT"):
                    self.registry.commit(run_id, list(existing.values()))
                result.registry_status = "COMMITTED"
            self.db.set_state("last_successful_run", run_id)
            return
        analysis = self.analyzer.analyze(list(new.values()))
        with self._job(run_id, "REPORT_GENERATION"), metrics.timer("report_generation_ms"):
            report = build_report(run_id, started, {"emails_scanned": result.emails_scanned,
                                  "emails_processed": result.emails_processed,
                                  "attachments_processed": result.attachments_processed},
                                  list(new.values()), list(existing.values()), result.failures, analysis)
            html_path, json_path = write_reports(report, self.s.report_output_dir)
            result.report_path = str(html_path)
        body = render_html(report)
        with metrics.timer("notification_ms"):
            try:
                with self._job(run_id, "EMAIL_NOTIFICATION"):
                    ok = self.notifier.send_alert(run_id, len(new), body, json.dumps(report, indent=2),
                                                  [(html_path.name, "text/html", html_path.read_bytes()),
                                                   (json_path.name, "application/json", json_path.read_bytes())])
                    if not ok:
                        raise RuntimeError("notification failed")
            except RuntimeError:
                ok = False
        if not ok:
            # Registry intentionally untouched; pending_errors keeps everything for the retry.
            result.notification_status, result.registry_status = "FAILED", "UNCHANGED"
            result.status = "notification_failed"
            result.failures.append("alert delivery failed; new errors remain pending for retry")
            return
        result.notification_status = "SENT"
        with self._job(run_id, "REGISTRY_COMMIT"), metrics.timer("registry_commit_ms"):
            self.registry.commit(run_id, list(merged.values()))
        result.registry_status = "COMMITTED"
        self.db.set_state("last_successful_run", run_id)

    # per-message work (runs in worker threads; no DB writes here) ---------------
    def _prepare(self, msg: EmailMessage, run_id: str, metrics: Metrics, cache, lock) -> MessageWork:
        work = MessageWork(msg)
        body = msg.body_text or _html_to_text(msg.body_html)
        self._scan(f"{msg.subject}\n{body}", msg, "", "email_body", run_id, work, metrics)
        with metrics.timer("attachment_download_ms"):
            metas = self.provider.list_attachments(msg.message_id)
        for meta in metas:
            entry = {"meta": meta, "sha": "", "status": "FAILED", "text": ""}
            work.attachments.append(entry)
            try:
                with metrics.timer("attachment_download_ms"):
                    data = self.provider.download_attachment(msg.message_id, meta.attachment_id)
                sha = hashlib.sha256(data).hexdigest()
                entry["sha"] = sha
                with lock:
                    hit = cache.get(sha)
                if hit:                                  # identical content: reuse extraction work
                    doc, findings, ai_status = hit
                else:
                    with self._extract_slots, metrics.timer("document_extraction_ms"):
                        doc = self.docs.extract(meta.filename, meta.mime_type, data, msg.message_id)
                    findings, ai_status = self._findings(doc.text, metrics) if doc.extraction_status == "SUCCESS" else ([], "SKIPPED")
                    with lock:
                        cache[sha] = (doc, findings, ai_status)
                entry["status"], entry["text"] = doc.extraction_status, doc.text
                if doc.extraction_status != "SUCCESS":
                    work.failures.append(f"{msg.message_id}:{doc.filename}: {doc.extraction_status} {doc.error_message}".strip())
                if ai_status == "FAILED":
                    work.failures.append(f"{msg.message_id}:{doc.filename}: AI enrichment incomplete")
                work.records.extend(self._records(findings, msg, doc.filename, "attachment", run_id))
            except Exception as exc:
                work.failures.append(f"{msg.message_id}:{meta.filename}: {type(exc).__name__}")
        return work

    def _findings(self, text: str, metrics: Metrics) -> tuple[list[RawFinding], str]:
        with metrics.timer("regex_extraction_ms"):
            found = self.regex.extract(text)
        if found:
            return found, "SKIPPED"
        with metrics.timer("llm_analysis_ms"):
            return self.ai.extract(text)

    def _scan(self, text, msg, att_name, source_type, run_id, work: MessageWork, metrics) -> None:
        findings, ai_status = self._findings(text, metrics)
        if ai_status == "FAILED":
            work.failures.append(f"{msg.message_id}: AI enrichment incomplete")
        work.records.extend(self._records(findings, msg, att_name, source_type, run_id))

    def _records(self, findings, msg, att_name, source_type, run_id) -> list[ErrorRecord]:
        out = []
        for f in findings:
            code = self.normalizer.normalize(f.canonical)
            if not code:
                continue
            out.append(ErrorRecord(
                raw_code=f.raw_code, normalized_code=code, message=f.message, context=f.context,
                severity=f.severity, source_message_id=msg.message_id, source_email=msg.sender,
                attachment_name=att_name, source_type=source_type, first_seen_at=msg.timestamp,
                last_seen_at=msg.timestamp, ai_confidence=f.confidence, run_id=run_id,
                sources=[f"{msg.message_id}:{att_name or 'body'}"]))
        return out

    # persistence -----------------------------------------------------------
    def _load_pending(self) -> dict[str, ErrorRecord]:
        with self.db.connection() as c:
            rows = c.execute("SELECT payload_json FROM pending_errors ORDER BY updated_at").fetchall()
        recs = [ErrorRecord.from_dict(json.loads(r["payload_json"])) for r in rows]
        return {r.normalized_code: r for r in recs}

    def _persist(self, run_id, started, works: list[MessageWork], current, pending) -> None:
        now = iso(utcnow())
        with self.db.transaction() as c:
            for w in works:
                m = w.msg
                c.execute("INSERT OR IGNORE INTO emails(message_id,thread_id,sender,subject,received_at,provider,"
                          "run_id,status,processed_at) VALUES(?,?,?,?,?,?,?, 'PROCESSED', ?)",
                          (m.message_id, m.thread_id, m.sender, m.subject, iso(m.timestamp), m.provider, run_id, now))
                for a in w.attachments:
                    meta = a["meta"]
                    c.execute("INSERT OR REPLACE INTO attachments(attachment_id,message_id,filename,mime_type,size,"
                              "sha256,local_path,processing_status,extracted_text,created_at) VALUES(?,?,?,?,?,?,NULL,?,?,?)",
                              (meta.attachment_id, m.message_id, meta.filename, meta.mime_type, meta.size,
                               a["sha"], a["status"], a["text"][:20000], now))
            c.executemany(
                "INSERT INTO extracted_errors(run_id,raw_code,normalized_code,message,context,severity,"
                "source_message_id,source_email,attachment_name,source_type,occurrence_count,first_seen_at,"
                "last_seen_at,ai_confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(run_id, r.raw_code, r.normalized_code, r.message, r.context, r.severity, r.source_message_id,
                  r.source_email, r.attachment_name, r.source_type, r.occurrence_count, iso(r.first_seen_at),
                  iso(r.last_seen_at), r.ai_confidence) for r in current.values()])
            for code, r in pending.items():
                c.execute("INSERT INTO pending_errors(normalized_code,payload_json,run_id,updated_at) VALUES(?,?,?,?) "
                          "ON CONFLICT(normalized_code) DO UPDATE SET payload_json=excluded.payload_json, "
                          "run_id=excluded.run_id, updated_at=excluded.updated_at",
                          (code, json.dumps(r.to_dict()), run_id, now))
            self.db.set_state_in(c, "last_scan_timestamp", iso(started))
