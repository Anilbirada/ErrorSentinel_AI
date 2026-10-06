from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ErrorRegistryEntry, GmailRegistryEntry
from app.errors.normalizer import normalize_code
from app.logging.logger import get_logger
from app.models.extraction import ErrorRecord
from app.models.registry import RegistryDecision, RegistryEntry, RegistryStatus

logger = get_logger("registry_repository")


class RegistryRepository:
    def __init__(self, session: Session, connection_id: Optional[str] = None):
        self.session = session
        self.connection_id = connection_id

    def codes(self) -> set[str]:
        """Return all normalized error codes currently in the registry."""
        if self.connection_id:
            rows = self.session.scalars(
                select(GmailRegistryEntry.code).where(
                    GmailRegistryEntry.connection_id == self.connection_id
                )
            ).all()
            return set(rows)
        rows = self.session.scalars(select(ErrorRegistryEntry.code)).all()
        return set(rows)

    def is_existing(self, code: str) -> bool:
        """Deterministic lookup: returns True if code exists in master registry."""
        norm = normalize_code(code)
        if not norm:
            return False
        if self.connection_id:
            stmt = select(GmailRegistryEntry).where(
                GmailRegistryEntry.connection_id == self.connection_id,
                GmailRegistryEntry.code == norm,
            )
            return self.session.scalar(stmt) is not None
        stmt = select(ErrorRegistryEntry).where(ErrorRegistryEntry.code == norm)
        return self.session.scalar(stmt) is not None

    def decide(self, code: str) -> RegistryDecision:
        """Deterministic authority: ONLY Python + Database decides NEW vs EXISTING."""
        return RegistryDecision.EXISTING if self.is_existing(code) else RegistryDecision.NEW

    def add(self, codes: Set[str], run_id: str = ""):
        """Add set of codes directly to registry."""
        for code in codes:
            normalized = normalize_code(code)
            if not normalized:
                continue
            if self.connection_id:
                stmt = select(GmailRegistryEntry).where(
                    GmailRegistryEntry.connection_id == self.connection_id,
                    GmailRegistryEntry.code == normalized,
                )
                existing = self.session.scalar(stmt)
                if existing is None:
                    self.session.add(
                        GmailRegistryEntry(
                            connection_id=self.connection_id,
                            code=normalized,
                            source_run_id=run_id,
                        )
                    )
                else:
                    existing.occurrence_count += 1
                    existing.last_seen_at = datetime.now(timezone.utc)
                continue
            stmt = select(ErrorRegistryEntry).where(ErrorRegistryEntry.code == normalized)
            existing = self.session.scalar(stmt)
            if not existing:
                entry = ErrorRegistryEntry(
                    code=normalized,
                    status="ACTIVE",
                    source="email_monitor",
                    source_run_id=run_id,
                    occurrence_count=1,
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                )
                self.session.add(entry)
            else:
                existing.occurrence_count += 1
                existing.last_seen_at = datetime.now(timezone.utc)
        self.session.flush()

    def commit_new_errors(
        self,
        errors: list[ErrorRecord],
        run_id: str,
        txt_path: Optional[Path] = None,
    ) -> list[str]:
        """
        MANDATORY TRANSACTION COMMIT.
        Must be called ONLY after verified successful notification delivery.
        Atomically updates SQLite error registry and synchronizes text registry.
        """
        committed_codes: list[str] = []
        now_dt = datetime.now(timezone.utc)

        try:
            for err in errors:
                norm = normalize_code(err.normalized_code or err.raw_code)
                if not norm:
                    continue

                if self.connection_id:
                    stmt = select(GmailRegistryEntry).where(
                        GmailRegistryEntry.connection_id == self.connection_id,
                        GmailRegistryEntry.code == norm,
                    )
                    existing = self.session.scalar(stmt)
                    if existing is None:
                        self.session.add(
                            GmailRegistryEntry(
                                connection_id=self.connection_id,
                                code=norm,
                                source_run_id=run_id,
                                occurrence_count=err.occurrence_count or 1,
                                first_seen_at=now_dt,
                                last_seen_at=now_dt,
                            )
                        )
                        committed_codes.append(norm)
                    else:
                        existing.occurrence_count += err.occurrence_count or 1
                        existing.last_seen_at = now_dt
                    continue

                stmt = select(ErrorRegistryEntry).where(ErrorRegistryEntry.code == norm)
                existing = self.session.scalar(stmt)

                if existing is None:
                    new_entry = ErrorRegistryEntry(
                        code=norm,
                        status="ACTIVE",
                        source=err.source_type or "email_monitor",
                        source_run_id=run_id,
                        occurrence_count=err.occurrence_count or 1,
                        first_seen_at=now_dt,
                        last_seen_at=now_dt,
                        created_at=now_dt,
                        updated_at=now_dt,
                    )
                    self.session.add(new_entry)
                    committed_codes.append(norm)
                else:
                    existing.occurrence_count += (err.occurrence_count or 1)
                    existing.last_seen_at = now_dt
                    existing.updated_at = now_dt

            self.session.commit()
            logger.info(f"Committed {len(committed_codes)} new error codes to registry for run {run_id}")

            # Sync to text file compatibility store
            if txt_path:
                self._sync_txt_file(txt_path)

            return committed_codes

        except Exception as e:
            self.session.rollback()
            logger.error(f"Registry commit transaction failed: {str(e)}", exc_info=True)
            raise

    def _sync_txt_file(self, txt_path: Path):
        try:
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            all_codes = sorted(self.codes())
            temp_file = txt_path.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write("\n".join(all_codes) + ("\n" if all_codes else ""))
            os.replace(temp_file, txt_path)
            logger.debug(f"Synchronized {len(all_codes)} codes to text registry: {txt_path}")
        except Exception as e:
            logger.warning(f"Failed syncing text registry file: {str(e)}")
