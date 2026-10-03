from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows console UTF-8 output if necessary
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import uvicorn

from app.config import get_settings, Settings
from app.database.session import init_db, SessionLocal, get_engine
from app.database.models import Base, ErrorRegistryEntry, ExtractedError, MonitoringRun, EmailRecord, AttachmentRecord
from app.logging.logger import get_logger, setup_logging
from app.models.jobs import JobStatus
from app.models.email import EmailMessage, EmailAttachment
from app.providers.demo.provider import DemoEmailProvider
from app.providers.factory import get_email_provider
from app.registry.repository import RegistryRepository
from app.registry.txt_registry import TxtRegistry
from app.services import MonitoringService

logger = get_logger("cli")


def run_server():
    """Start the FastAPI server + Dashboard + Background Scheduler."""
    settings = get_settings()
    setup_logging(settings.log_level)
    print("=" * 70)
    print(" RSR ErrorSentinel AI -- Email Error Intelligence & Monitoring Agent")
    print(" Tagline: Detect. Understand. Verify. Alert.")
    print("=" * 70)
    print(f" Web Dashboard: http://{settings.host if settings.host != '0.0.0.0' else '127.0.0.1'}:{settings.port}")
    print(f" REST API Docs: http://{settings.host if settings.host != '0.0.0.0' else '127.0.0.1'}:{settings.port}/docs")
    print(f" Provider:     {settings.email_provider.upper()}")
    print(f" Database:     {settings.database_url}")
    print(f" Scheduler:    Every {settings.monitor_interval_minutes} minutes")
    print("=" * 70)

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


def run_now():
    """Trigger an immediate single monitoring cycle."""
    init_db()
    settings = get_settings()
    service = MonitoringService(settings)
    print("\n[*] Triggering immediate monitoring cycle...")
    result = service.execute_monitoring_cycle()

    print("\n" + "=" * 50)
    print(" MONITORING RUN COMPLETED")
    print("=" * 50)
    print(f" Run ID:                {result.run_id}")
    print(f" Status:                {result.status.value}")
    print(f" Emails Scanned:        {result.emails_scanned}")
    print(f" Emails Processed:      {result.emails_processed}")
    print(f" Attachments Processed: {result.attachments_processed}")
    print(f" Total Extracted:       {result.errors_extracted}")
    print(f" NEW Errors Detected:   {result.new_errors_count}")
    print(f" Existing/Known Errors: {result.existing_errors_count}")
    print(f" Notification Status:   {result.notification_status}")
    print(f" Registry Status:       {result.registry_status}")
    print(f" Total Duration:        {result.duration_ms:.2f} ms")
    if result.error_message:
        print(f" Error Detail:          {result.error_message}")
    print("=" * 50 + "\n")


def check_config():
    """Validate current environment and provider configurations."""
    settings = get_settings()
    print("\n" + "=" * 60)
    print(" RSR ErrorSentinel AI -- Configuration Preflight Check")
    print("=" * 60)
    print(f" Environment:        {settings.app_env}")
    print(f" Email Provider:     {settings.email_provider}")
    print(f" LLM Provider:       {settings.active_llm_provider} ({settings.active_llm_model})")
    print(f" Database URL:       {settings.database_url}")
    print(f" Monitor Interval:   {settings.monitor_interval_minutes} mins")

    print("\n--- Gmail Provider Status ---")
    if settings.gmail_ready:
        print(" [OK] Gmail configuration ready.")
    else:
        print(f" [WARNING] Gmail missing: {', '.join(settings.missing_gmail_settings)}")

    print("\n--- Microsoft Graph Provider Status ---")
    if settings.graph_ready:
        print(" [OK] Microsoft Graph configuration ready.")
    else:
        print(f" [INFO] Microsoft Graph inactive / missing: {', '.join(settings.missing_graph_settings)}")

    print("\n--- AI Provider Status ---")
    if settings.active_llm_provider in ("mock", "disabled"):
        print(f" [OK] Using safe built-in {settings.active_llm_provider} AI mode.")
    elif settings.active_llm_key:
        print(f" [OK] LLM API key configured for {settings.active_llm_provider}.")
    else:
        print(f" [WARNING] LLM provider '{settings.active_llm_provider}' has no API key set.")
    print("=" * 60 + "\n")


def show_status():
    """Display system status, error counts, and recent runs."""
    init_db()
    with SessionLocal() as db:
        reg_repo = RegistryRepository(db)
        codes = sorted(reg_repo.codes())
        print("\n" + "=" * 50)
        print(" RSR ErrorSentinel AI -- System Status")
        print("=" * 50)
        print(f" Total Registered Error Codes: {len(codes)}")
        if codes:
            print(f" Sample Codes: {', '.join(codes[:10])}{' ...' if len(codes) > 10 else ''}")
        print("=" * 50 + "\n")


def test_email():
    """Send a test alert email through the configured provider."""
    init_db()
    settings = get_settings()
    provider = get_email_provider(settings=settings)
    print(f"\n[*] Testing email delivery via provider '{provider.provider_name}'...")

    recipients = settings.recipients or [settings.monitor_mailbox or "test@rsr.internal"]
    subject = "[RSR ErrorSentinel AI] Connectivity Test Alert"
    html = "<h3>RSR ErrorSentinel AI</h3><p>This is a test notification confirming email alerting connectivity.</p>"

    success = provider.send_alert(
        recipients=recipients,
        subject=subject,
        body_html=html,
        body_text="This is a test notification from RSR ErrorSentinel AI.",
    )

    if success:
        print(f" [SUCCESS] Test email successfully delivered to {recipients}!")
    else:
        print(f" [FAILED] Test email delivery failed. Check credentials and provider logs.")


def run_demo():
    """
    Complete Standalone End-to-End Demo Mode.
    Simulates the full business workflow without needing Gmail, Graph, or external LLM APIs.
    """
    print("\n" + "=" * 70)
    print(" RSR ErrorSentinel AI -- INTERACTIVE DEMO MODE")
    print(" Tagline: Detect. Understand. Verify. Alert.")
    print("=" * 70)

    init_db()
    settings = get_settings()

    # Clean test registry file and DB table for an isolated reproducible demo run
    temp_txt_registry = settings.reports_dir / "demo_registry.txt"
    if temp_txt_registry.exists():
        temp_txt_registry.unlink()
    settings.registry_file = temp_txt_registry

    with SessionLocal() as db:
        db.query(ErrorRegistryEntry).delete()
        db.query(ExtractedError).delete()
        db.query(EmailRecord).delete()
        db.query(AttachmentRecord).delete()
        db.commit()

    demo_provider = DemoEmailProvider(settings)
    service = MonitoringService(settings, provider=demo_provider)

    # STEP 1: First scan with 2 new errors (ERR-5021, ERR-7788)
    print("\n[STEP 1] Running first scan on Demo Inbox...")
    print("         Contains: production.log with ERR-5021 and ERR-7788")
    run1 = service.execute_monitoring_cycle(provider_override=demo_provider)
    print(f"         Result: Scanned={run1.emails_scanned}, Extracted={run1.errors_extracted}")
    print(f"                 NEW Errors Detected: {run1.new_errors_count} (Expected: 2)")
    print(f"                 Notification Status: {run1.notification_status} (Expected: SENT)")
    print(f"                 Registry Status:     {run1.registry_status} (Expected: COMMITTED)")
    assert run1.new_errors_count == 2, f"Expected 2 new errors, got {run1.new_errors_count}"
    assert run1.registry_status == "COMMITTED"
    print("         [PASS] Step 1 Passed: 2 new errors detected, alert sent, registry committed.")

    # STEP 2: Second scan with identical emails
    print("\n[STEP 2] Running second scan with identical email content...")
    demo_provider2 = DemoEmailProvider(settings)
    run2 = service.execute_monitoring_cycle(provider_override=demo_provider2)
    print(f"         Result: Scanned={run2.emails_scanned}")
    print(f"                 NEW Errors Detected: {run2.new_errors_count} (Expected: 0)")
    print(f"                 Existing Errors:     {run2.existing_errors_count}")
    print(f"                 Registry Status:     {run2.registry_status} (Expected: UNCHANGED)")
    assert run2.new_errors_count == 0, f"Expected 0 new errors, got {run2.new_errors_count}"
    print("         [PASS] Step 2 Passed: 0 new errors detected. Known errors filtered deterministically.")

    # STEP 3: Add new error ERR-9001 and simulate notification failure
    print("\n[STEP 3] Injecting new error ERR-9001 with SIMULATED NOTIFICATION FAILURE...")
    demo_provider3 = DemoEmailProvider(settings)
    msg_new = EmailMessage(
        message_id="demo_msg_002",
        sender="auth-service@rsr.internal",
        recipients=["ops@rsr.internal"],
        subject="[Critical] API Authentication Failure",
        body_text="ERR-9001 API authentication failure with OAuth token expiry.",
        provider="demo",
    )
    demo_provider3.add_custom_message(msg_new)
    demo_provider3.should_fail_send = True  # Simulate delivery network failure

    run3 = service.execute_monitoring_cycle(provider_override=demo_provider3)
    print(f"         Result: NEW Errors Detected: {run3.new_errors_count} (Expected: 1 - ERR-9001)")
    print(f"                 Notification Status: {run3.notification_status} (Expected: FAILED)")
    print(f"                 Registry Status:     {run3.registry_status} (Expected: UNCHANGED)")
    assert run3.new_errors_count == 1, f"Expected 1 new error, got {run3.new_errors_count}"

    # Verify ERR-9001 is NOT in master registry
    with SessionLocal() as db:
        repo = RegistryRepository(db)
        is_in_registry = repo.is_existing("ERR-9001")
        print(f"         Verification: Is ERR-9001 in registry? {is_in_registry} (Expected: False)")
        assert not is_in_registry, "MANDATORY TRANSACTION VIOLATION: Registry was updated despite notification failure!"

    print("         [PASS] Step 3 Passed: MANDATORY TRANSACTION RULE ENFORCED. Registry remained unchanged.")

    # STEP 4: Retry with notification restored to success
    print("\n[STEP 4] Retrying scan with notification connection restored...")
    demo_provider3.should_fail_send = False

    # Clear email_records processed status for demo_msg_002 so it reprocesses cleanly
    with SessionLocal() as db:
        email_rec = db.get(EmailRecord, "demo_msg_002")
        if email_rec:
            email_rec.processing_status = "PENDING"
            db.commit()

    run4 = service.execute_monitoring_cycle(provider_override=demo_provider3)
    print(f"         Result: NEW Errors Detected: {run4.new_errors_count} (Expected: 1 - ERR-9001)")
    print(f"                 Notification Status: {run4.notification_status} (Expected: SENT)")
    print(f"                 Registry Status:     {run4.registry_status} (Expected: COMMITTED)")
    assert run4.new_errors_count == 1, f"Expected 1 new error, got {run4.new_errors_count}"

    with SessionLocal() as db:
        repo = RegistryRepository(db)
        is_in_registry = repo.is_existing("ERR-9001")
        print(f"         Verification: Is ERR-9001 now in registry? {is_in_registry} (Expected: True)")
        assert is_in_registry, "ERR-9001 should be committed after successful notification"

    print("         [PASS] Step 4 Passed: Successful retry committed ERR-9001 to registry.")

    print("\n" + "=" * 70)
    print("  DEMO MODE VERIFICATION COMPLETED SUCCESSFULLY!")
    print(" All business rules, deterministic filtering, and atomic delivery")
    print(" transaction guarantees have been verified.")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="RSR ErrorSentinel AI -- Email Error Intelligence & Monitoring Agent"
    )
    parser.add_argument("--run-now", action="store_true", help="Execute single monitoring cycle immediately")
    parser.add_argument("--demo", action="store_true", help="Run end-to-end self-contained demo mode")
    parser.add_argument("--check-config", action="store_true", help="Validate current configuration & provider setup")
    parser.add_argument("--status", action="store_true", help="Display system statistics and registry status")
    parser.add_argument("--test-email", action="store_true", help="Send a test alert email via configured provider")

    args = parser.parse_args()

    if args.demo:
        run_demo()
    elif args.run_now:
        run_now()
    elif args.check_config:
        check_config()
    elif args.status:
        show_status()
    elif args.test_email:
        test_email()
    else:
        run_server()


if __name__ == "__main__":
    main()
