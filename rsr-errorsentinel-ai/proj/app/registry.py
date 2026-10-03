"""Master error registry. The ONLY place that decides NEW vs EXISTING (never the LLM)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Iterable

from .database import Database
from .models import ErrorRecord, iso, utcnow
from .normalization import Normalizer

log = logging.getLogger("sentinel.registry")


class Registry:
    def __init__(self, db: Database, normalizer: Normalizer) -> None:
        self.db = db
        self.normalizer = normalizer
        self._test_hook: Callable[[], None] | None = None  # fault injection for rollback tests

    def seed_from_file(self, path: str | Path) -> int:
        """Import data/existing_error_codes.txt (one code per line). Idempotent."""
        p = Path(path)
        if not p.is_file():
            return 0
        codes = {self.normalizer.normalize(line) for line in p.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.strip().startswith("#")}
        codes.discard("")
        now = iso(utcnow())
        with self.db.transaction() as conn:
            before = conn.execute("SELECT COUNT(*) c FROM error_registry").fetchone()["c"]
            conn.executemany(
                "INSERT OR IGNORE INTO error_registry(normalized_code, first_seen_at, last_seen_at, "
                "occurrence_count, status, source, created_at, updated_at) VALUES(?,?,?,0,'ACTIVE','seed_file',?,?)",
                [(c, now, now, now, now) for c in sorted(codes)])
            after = conn.execute("SELECT COUNT(*) c FROM error_registry").fetchone()["c"]
        log.info("registry seeded from file: %d new codes", after - before)
        return after - before

    def known_codes(self, codes: Iterable[str]) -> set[str]:
        """Deterministic bulk lookup."""
        codes = list(set(codes))
        found: set[str] = set()
        with self.db.connection() as conn:
            for i in range(0, len(codes), 500):
                chunk = codes[i:i + 500]
                q = ",".join("?" * len(chunk))
                found.update(r["normalized_code"] for r in conn.execute(
                    f"SELECT normalized_code FROM error_registry WHERE normalized_code IN ({q})", chunk))
        return found

    def all_codes(self) -> list[str]:
        with self.db.connection() as conn:
            return [r["normalized_code"] for r in conn.execute(
                "SELECT normalized_code FROM error_registry ORDER BY normalized_code")]

    def commit(self, run_id: str, records: list[ErrorRecord], source: str = "detected") -> int:
        """Atomically add new codes / bump counts / clear pending. Idempotent per run_id.

        Returns the number of codes newly inserted. On any failure everything rolls back.
        """
        now = iso(utcnow())
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM registry_commits WHERE run_id=?", (run_id,)).fetchone():
                log.info("registry commit for %s already applied; skipping", run_id)
                return 0
            codes = [r.normalized_code for r in records]
            existing: set[str] = set()
            for i in range(0, len(codes), 500):
                chunk = codes[i:i + 500]
                existing.update(r["normalized_code"] for r in conn.execute(
                    f"SELECT normalized_code FROM error_registry WHERE normalized_code IN ({','.join('?' * len(chunk))})",
                    chunk))
            added = sum(1 for c in codes if c not in existing)
            conn.executemany(
                "INSERT INTO error_registry(normalized_code, first_seen_at, last_seen_at, occurrence_count, "
                "status, source, created_at, updated_at) VALUES(?,?,?,?, 'ACTIVE', ?, ?, ?) "
                "ON CONFLICT(normalized_code) DO UPDATE SET "
                "occurrence_count = occurrence_count + excluded.occurrence_count, "
                "last_seen_at = MAX(last_seen_at, excluded.last_seen_at), updated_at = excluded.updated_at",
                [(r.normalized_code, iso(r.first_seen_at), iso(r.last_seen_at), r.occurrence_count,
                  f"{source}:{run_id}", now, now) for r in records])
            if self._test_hook:
                self._test_hook()
            conn.execute("INSERT INTO registry_commits(run_id, committed_at, codes_added) VALUES(?,?,?)",
                         (run_id, now, added))
            conn.executemany("DELETE FROM pending_errors WHERE normalized_code=?", [(c,) for c in codes])
            self.db.set_state_in(conn, "last_registry_commit", run_id)
        log.info("registry committed run=%s added=%d updated=%d", run_id, added, len(codes) - added)
        return added
