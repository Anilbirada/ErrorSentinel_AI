from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import EmailRecord, ProcessingStateRecord
from app.logging.logger import get_logger

logger = get_logger("state_manager")


class StateManager:
    def __init__(self, session: Session):
        self.session = session

    def get_state(self, key: str, default: Any = None) -> Any:
        stmt = select(ProcessingStateRecord).where(ProcessingStateRecord.id == key)
        record = self.session.scalar(stmt)
        if not record or not record.value:
            return default
        try:
            return json.loads(record.value)
        except Exception:
            return record.value

    def set_state(self, key: str, value: Any):
        stmt = select(ProcessingStateRecord).where(ProcessingStateRecord.id == key)
        record = self.session.scalar(stmt)
        str_val = json.dumps(value) if not isinstance(value, str) else value
        now_dt = datetime.now(timezone.utc)

        if not record:
            record = ProcessingStateRecord(id=key, value=str_val, updated_at=now_dt)
            self.session.add(record)
        else:
            record.value = str_val
            record.updated_at = now_dt
        self.session.commit()

    def is_message_processed(self, message_id: str) -> bool:
        stmt = select(EmailRecord).where(EmailRecord.id == message_id)
        row = self.session.scalar(stmt)
        return row is not None and row.processing_status in ("PROCESSED", "SUCCESS", "COMPLETED")

    def mark_message_processed(
        self,
        message_id: str,
        run_id: str,
        sender: str = "",
        subject: str = "",
        recipients: str = "",
        has_attachments: bool = False,
        provider: str = "gmail",
        status: str = "PROCESSED",
    ):
        stmt = select(EmailRecord).where(EmailRecord.id == message_id)
        row = self.session.scalar(stmt)
        now_dt = datetime.now(timezone.utc)

        if not row:
            row = EmailRecord(
                id=message_id,
                run_id=run_id,
                sender=sender,
                subject=subject,
                recipients=recipients,
                has_attachments=has_attachments,
                provider=provider,
                processed_at=now_dt,
                processing_status=status,
            )
            self.session.add(row)
        else:
            row.run_id = run_id
            row.processed_at = now_dt
            row.processing_status = status
        self.session.commit()

    def get_last_scan_timestamp(self) -> Optional[str]:
        return self.get_state("last_scan_timestamp")

    def set_last_scan_timestamp(self, ts: str):
        self.set_state("last_scan_timestamp", ts)

    def record_run_completion(self, run_id: str, is_success: bool):
        if is_success:
            self.set_state("last_successful_run", run_id)
            self.set_state("last_successful_run_time", datetime.now(timezone.utc).isoformat())
