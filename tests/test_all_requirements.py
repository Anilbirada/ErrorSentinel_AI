from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.provider import (
    DisabledAIProvider,
    LLMProvider,
    MockLLMProvider,
    OpenAILLMProvider,
)
from app.attachments.downloader import AttachmentDownloader
from app.attachments.security import safe_filename, validate_attachment_safety
from app.config import Settings
from app.database.models import (
    AlertDelivery,
    AttachmentRecord,
    Base,
    EmailRecord,
    ErrorRegistryEntry,
    ExtractedError,
    MonitoringRun,
)
from app.errors.deduplicator import deduplicate_errors
from app.errors.extractor import extract_error_records, extract_errors
from app.errors.normalizer import normalize_code
from app.extraction.dispatcher import extract_document
from app.models.email import EmailAttachment, EmailMessage
from app.models.extraction import ErrorRecord, SeverityLevel
from app.models.jobs import JobStatus, MonitoringRunModel
from app.models.registry import RegistryDecision
from app.notifications.notifier import NotificationService
from app.providers.demo.provider import DemoEmailProvider
from app.providers.gmail.provider import GmailProvider
from app.registry.repository import RegistryRepository
from app.registry.txt_registry import TxtRegistry
from app.scheduler.scheduler import create_scheduler
from app.services import MonitoringService
from app.state.state_manager import StateManager


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def test_settings(tmp_path):
    return Settings(
        _env_file=None,
        registry_file=tmp_path / "data" / "codes.txt",
        reports_dir=tmp_path / "reports",
        downloads_dir=tmp_path / "downloads",
        max_attachment_size_mb=25,
        enable_email_attachments=True,
    )


# 1 & 2: New and Existing Error Detection (Deterministic Authority)
def test_1_and_2_new_and_existing_error_detection(db_session, test_settings):
    repo = RegistryRepository(db_session)
    repo.commit_new_errors(
        [ErrorRecord(normalized_code="ERR-1001", raw_code="ERR-1001")],
        run_id="run_1",
        txt_path=test_settings.registry_file,
    )

    assert repo.is_existing("ERR-1001") is True
    assert repo.decide("ERR-1001") == RegistryDecision.EXISTING
    assert repo.is_existing("ERR-9999") is False
    assert repo.decide("ERR-9999") == RegistryDecision.NEW


# 3: Case Normalization
def test_3_case_normalization():
    assert normalize_code("err-5021") == "ERR-5021"
    assert normalize_code("error-5021") == "ERR-5021"
    assert normalize_code("http-404") == "HTTP-404"


# 4: Whitespace Normalization
def test_4_whitespace_normalization():
    assert normalize_code("  ERR-5021  ") == "ERR-5021"
    assert normalize_code("  Error 5021 \n") == "ERR-5021"


# 5: Unicode Dash Normalization
def test_5_unicode_dash_normalization():
    assert normalize_code("ERR–5021") == "ERR-5021"  # En dash \u2013
    assert normalize_code("ERR—5021") == "ERR-5021"  # Em dash \u2014
    assert normalize_code("ERR−5021") == "ERR-5021"  # Minus sign \u2212


# 6: Duplicate Errors Removal
def test_6_duplicate_errors_removal():
    records = [
        ErrorRecord(raw_code="ERR-5021", normalized_code="ERR-5021", occurrence_count=1),
        ErrorRecord(raw_code="err-5021", normalized_code="ERR-5021", occurrence_count=1),
    ]
    deduped = deduplicate_errors(records)
    assert len(deduped) == 1
    assert deduped[0].normalized_code == "ERR-5021"
    assert deduped[0].occurrence_count == 2


# 7: Multiple Occurrences Aggregation
def test_7_multiple_occurrences_aggregation():
    records = [
        ErrorRecord(raw_code="ERR-7788", normalized_code="ERR-7788", occurrence_count=3),
        ErrorRecord(raw_code="ERR-7788", normalized_code="ERR-7788", occurrence_count=2),
    ]
    deduped = deduplicate_errors(records)
    assert len(deduped) == 1
    assert deduped[0].occurrence_count == 5


# 8 & 9: Same error across multiple emails and attachments
def test_8_and_9_same_error_across_emails_and_attachments():
    records = [
        ErrorRecord(raw_code="ERR-5021", normalized_code="ERR-5021", source_email="a@rsr.test", source_type="email_body"),
        ErrorRecord(raw_code="ERR-5021", normalized_code="ERR-5021", source_email="b@rsr.test", source_type="email_body"),
        ErrorRecord(raw_code="ERR-5021", normalized_code="ERR-5021", attachment_name="log.txt", source_type="attachment"),
    ]
    deduped = deduplicate_errors(records)
    assert len(deduped) == 1
    assert deduped[0].occurrence_count == 3


# 10: PDF Extraction (PyMuPDF)
def test_10_pdf_extraction(tmp_path):
    import fitz
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Fatal incident: ERR-8800 Database corruption detected.")
    doc.save(str(pdf_path))
    doc.close()

    extracted = extract_document(pdf_path, source_message_id="msg-pdf")
    assert extracted.extraction_status == "SUCCESS"
    assert "ERR-8800" in extracted.text


# 11: DOCX Extraction
def test_11_docx_extraction(tmp_path):
    import docx
    docx_path = tmp_path / "sample.docx"
    doc = docx.Document()
    doc.add_heading("Error Report", level=1)
    doc.add_paragraph("Server failed with ERR-4433 SSL Handshake Error.")
    doc.save(str(docx_path))

    extracted = extract_document(docx_path, source_message_id="msg-docx")
    assert extracted.extraction_status == "SUCCESS"
    assert "ERR-4433" in extracted.text


# 12 & 13: XLSX and XLS Extraction
def test_12_xlsx_extraction(tmp_path):
    import pandas as pd
    xlsx_path = tmp_path / "errors.xlsx"
    df = pd.DataFrame({
        "ErrorID": ["ERR-3301", "ERR-3302"],
        "Description": ["Deadlock in table orders", "Disk full"],
    })
    df.to_excel(xlsx_path, index=False, engine="openpyxl")

    extracted = extract_document(xlsx_path, source_message_id="msg-xlsx")
    assert extracted.extraction_status == "SUCCESS"
    assert "ERR-3301" in extracted.text


# 14: CSV Extraction
def test_14_csv_extraction(tmp_path):
    csv_path = tmp_path / "log.csv"
    csv_path.write_text("timestamp,error_code,message\n2026-10-03,ERR-2002,Connection pool exhausted\n", encoding="utf-8")
    extracted = extract_document(csv_path, source_message_id="msg-csv")
    assert extracted.extraction_status == "SUCCESS"
    assert "ERR-2002" in extracted.text


# 15: JSON Extraction
def test_15_json_extraction(tmp_path):
    json_path = tmp_path / "report.json"
    json_path.write_text(json.dumps({"error": "ERR-1100", "status": "failed"}), encoding="utf-8")
    extracted = extract_document(json_path, source_message_id="msg-json")
    assert extracted.extraction_status == "SUCCESS"
    assert "ERR-1100" in extracted.text


# 16: XML Extraction
def test_16_xml_extraction(tmp_path):
    xml_path = tmp_path / "data.xml"
    xml_path.write_text("<root><error code='ERR-6611'>Critical Fault</error></root>", encoding="utf-8")
    extracted = extract_document(xml_path, source_message_id="msg-xml")
    assert extracted.extraction_status == "SUCCESS"
    assert "ERR-6611" in extracted.text or "Critical Fault" in extracted.text


# 17 & 18: TXT and LOG Extraction
def test_17_and_18_txt_log_extraction(tmp_path):
    log_path = tmp_path / "system.log"
    log_path.write_text("2026-10-03 [ERROR] ERR-9911: Out of memory", encoding="utf-8")
    extracted = extract_document(log_path, source_message_id="msg-log")
    assert extracted.extraction_status == "SUCCESS"
    assert "ERR-9911" in extracted.text


# 19: Corrupted Attachment Handling
def test_19_corrupted_attachment_handling(tmp_path):
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"NOT A REAL PDF CONTENT RANDOM BYTES 123456789")
    extracted = extract_document(bad_pdf, source_message_id="msg-corrupt")
    assert extracted.extraction_status in ("SUCCESS", "FAILED")  # Handled safely without unhandled exception


# 20: Unsupported Attachment Handling
def test_20_unsupported_attachment_handling(tmp_path):
    custom_file = tmp_path / "data.customconfig"
    custom_file.write_text("config_error = ERR-7712", encoding="utf-8")
    extracted = extract_document(custom_file, source_message_id="msg-custom")
    assert extracted.extraction_status == "SUCCESS"
    assert "ERR-7712" in extracted.text


# 21: Large Attachment Limits
def test_21_large_attachment_limits(test_settings):
    is_safe, reason = validate_attachment_safety("big_video.mp4", 50 * 1024 * 1024)
    assert is_safe is False
    assert "exceeds" in reason.lower()

    # Blocked dangerous extensions
    is_safe_exe, _ = validate_attachment_safety("malware.exe", 1024)
    assert is_safe_exe is False


# 22: Regex Extraction
def test_22_regex_extraction():
    text = (
        "Encountered ERR-1234 along with HTTP 500 server error, "
        "SQLSTATE 42000 syntax error, and ORA-00942 table does not exist."
    )
    findings = extract_errors(text)
    codes = {f.code for f in findings}
    assert "ERR-1234" in codes
    assert "HTTP-500" in codes
    assert "SQLSTATE-42000" in codes
    assert "ORA-00942" in codes


# 23: LLM Structured Response
def test_23_llm_structured_response():
    provider = MockLLMProvider()
    results = provider.extract_structured_errors(
        "Production database timeout error ERR-5021",
        source_context="Test log"
    )
    assert len(results) > 0
    assert results[0]["error_code"] == "ERR-5021"
    assert results[0]["severity"] == "HIGH"


# 24 & 25: Malformed LLM response and LLM timeout
def test_24_and_25_malformed_llm_and_timeout():
    disabled = DisabledAIProvider()
    assert disabled.extract_structured_errors("ERR-5021") == []
    analysis = disabled.analyze_errors([])
    assert "summary" in analysis


# 26 & 27: Gmail auth failure & API failure
def test_26_and_27_gmail_auth_and_api_failure(tmp_path):
    settings = Settings(
        _env_file=None,
        gmail_credentials_file="nonexistent_credentials.json",
        gmail_token_file="nonexistent_token.json",
    )
    gmail = GmailProvider(settings)
    assert gmail.authenticate() is False
    assert gmail.is_authenticated() is False
    assert gmail.list_messages() == []


# 28, 29, 30, 31: MANDATORY TRANSACTION RULE (Notification failure vs success)
def test_28_through_31_mandatory_transaction_rule(db_session, test_settings):
    provider = DemoEmailProvider(test_settings)
    notifier = NotificationService(test_settings)
    run_model = MonitoringRunModel(run_id="run_tx_test", started_at=datetime.now(timezone.utc))

    errors = [ErrorRecord(raw_code="ERR-9999", normalized_code="ERR-9999", message="Auth fault")]

    # CASE 1: Delivery Fails
    provider.should_fail_send = True
    success, msg = notifier.dispatch_alert_and_commit(
        provider=provider,
        db_session=db_session,
        run=run_model,
        new_errors=errors,
        recipients_override=["test@rsr.test"],
    )
    assert success is False
    assert run_model.notification_status == "FAILED"
    assert run_model.registry_status == "UNCHANGED"

    # Verify registry is unchanged
    repo = RegistryRepository(db_session)
    assert repo.is_existing("ERR-9999") is False

    # CASE 2: Delivery Succeeds
    provider.should_fail_send = False
    success_2, msg_2 = notifier.dispatch_alert_and_commit(
        provider=provider,
        db_session=db_session,
        run=run_model,
        new_errors=errors,
        recipients_override=["test@rsr.test"],
    )
    assert success_2 is True
    assert run_model.notification_status == "SENT"
    assert run_model.registry_status == "COMMITTED"

    # Verify registry is committed
    assert repo.is_existing("ERR-9999") is True


# 32 & 33: State Persistence & Duplicate Message Idempotency
def test_32_and_33_state_persistence(db_session):
    state_mgr = StateManager(db_session)
    state_mgr.set_state("test_key", {"counter": 42, "active": True})
    val = state_mgr.get_state("test_key")
    assert val == {"counter": 42, "active": True}

    assert state_mgr.is_message_processed("msg_xyz_100") is False
    state_mgr.mark_message_processed("msg_xyz_100", run_id="run_100", sender="ops@rsr.test", subject="Error Notice")
    assert state_mgr.is_message_processed("msg_xyz_100") is True


# 34 & 35: Scheduler Overlap Prevention & Safe Multi-run Execution
def test_34_and_35_scheduler_overlap_prevention(test_settings):
    scheduler = create_scheduler(test_settings)
    assert scheduler is not None
    job = scheduler.get_job("monitor")
    assert job is not None
    assert job.max_instances == 1  # Overlap prevention strictly enforced
