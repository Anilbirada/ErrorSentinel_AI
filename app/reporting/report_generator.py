from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Optional

from app.config import Settings, get_settings
from app.logging.logger import get_logger
from app.models.extraction import ErrorRecord
from app.models.jobs import MonitoringRunModel

logger = get_logger("report_generator")


def generate_html_report(
    run: MonitoringRunModel,
    new_errors: list[ErrorRecord],
    existing_errors: list[ErrorRecord],
    ai_analysis: Optional[dict[str, Any]] = None,
    settings: Optional[Settings] = None,
) -> str:
    cfg = settings or get_settings()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Severity badges helper
    def sev_badge(sev: str) -> str:
        s = sev.upper()
        colors = {
            "CRITICAL": "#dc2626; background: #fee2e2",
            "HIGH": "#ea580c; background: #ffedd5",
            "MEDIUM": "#d97706; background: #fef3c7",
            "LOW": "#2563eb; background: #dbeafe",
            "INFO": "#4b5563; background: #f3f4f6",
        }
        style = colors.get(s, "#4b5563; background: #f3f4f6")
        return f'<span style="padding:3px 8px; border-radius:4px; font-weight:600; font-size:12px; color:{style}">{escape(s)}</span>'

    # Build error table rows
    table_rows = []
    for err in sorted(new_errors, key=lambda x: x.normalized_code):
        table_rows.append(f"""
        <tr>
            <td><strong style="color:#0f172a; font-family:monospace; font-size:14px;">{escape(err.normalized_code)}</strong></td>
            <td>{sev_badge(str(err.severity))}</td>
            <td style="text-align:center;"><span style="background:#e2e8f0; padding:2px 8px; border-radius:12px; font-weight:bold;">{err.occurrence_count}</span></td>
            <td>{escape(err.message or err.raw_code)}</td>
            <td>
                <div style="font-family:monospace; font-size:12px; background:#f8fafc; border:1px solid #e2e8f0; padding:6px; border-radius:4px; max-height:120px; overflow-y:auto; white-space:pre-wrap;">{escape(err.context or "N/A")}</div>
            </td>
            <td style="font-size:12px;">
                <b>Email:</b> {escape(err.source_email or "Unknown")}<br>
                <b>Sender:</b> {escape(err.sender or "N/A")}<br>
                <b>Attachment:</b> {escape(err.attachment_name or "N/A")}
            </td>
        </tr>
        """)

    rows_html = "".join(table_rows) if table_rows else '<tr><td colspan="6" style="text-align:center; padding:20px; color:#64748b;">No new error signatures detected in this run.</td></tr>'

    # AI Section HTML
    ai_html = ""
    if ai_analysis and ai_analysis.get("summary"):
        actions_li = "".join(f"<li>{escape(a)}</li>" for a in ai_analysis.get("suggested_actions", []))
        ai_html = f"""
        <div style="background:#eff6ff; border-left:4px solid #3b82f6; padding:16px 20px; margin:24px 0; border-radius:0 8px 8px 0;">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                <span style="background:#3b82f6; color:#fff; font-size:11px; font-weight:bold; padding:2px 8px; border-radius:4px;">AI INTERPRETATION</span>
                <span style="color:#64748b; font-size:12px;">(Automated Root Cause Assessment — Review with Engineering)</span>
            </div>
            <p style="margin:0 0 10px 0; font-size:14px; color:#1e293b; line-height:1.5;"><strong>Summary:</strong> {escape(ai_analysis.get('summary', ''))}</p>
            <p style="margin:0 0 10px 0; font-size:14px; color:#1e293b; line-height:1.5;"><strong>Root Cause Assessment:</strong> {escape(ai_analysis.get('root_cause_assessment', ''))}</p>
            {f'<div style="margin-top:10px;"><strong style="font-size:13px; color:#1e293b;">Suggested Investigation Areas:</strong><ul style="margin:6px 0 0 20px; font-size:13px; color:#334155;">{actions_li}</ul></div>' if actions_li else ''}
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RSR ErrorSentinel AI — Error Intelligence Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #1e293b; background-color: #f8fafc; margin: 0; padding: 24px; }}
        .container {{ max-width: 1100px; margin: 0 auto; background: #ffffff; border-radius: 10px; border: 1px solid #e2e8f0; padding: 32px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
        .header {{ border-bottom: 2px solid #0f172a; padding-bottom: 16px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-start; }}
        .title {{ font-size: 24px; font-weight: 800; color: #0f172a; margin: 0; }}
        .tagline {{ font-size: 13px; color: #64748b; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }}
        .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; background: #f1f5f9; padding: 16px; border-radius: 8px; }}
        .meta-item {{ font-size: 13px; }}
        .meta-label {{ color: #64748b; margin-bottom: 2px; }}
        .meta-val {{ font-weight: 700; color: #0f172a; font-size: 15px; }}
        .badge-new {{ background: #fee2e2; color: #b91c1c; padding: 2px 10px; border-radius: 12px; font-weight: 800; }}
        .section-title {{ font-size: 17px; font-weight: 700; color: #0f172a; margin: 24px 0 12px 0; display: flex; align-items: center; justify-content: space-between; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
        th {{ background: #0f172a; color: #ffffff; font-weight: 600; text-align: left; padding: 10px 12px; font-size: 13px; }}
        td {{ padding: 12px; border-bottom: 1px solid #e2e8f0; vertical-align: top; font-size: 13px; }}
        tr:hover {{ background-color: #f8fafc; }}
        .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; display: flex; justify-content: space-between; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1 class="title">RSR ErrorSentinel AI</h1>
                <div class="tagline">Detect. Understand. Verify. Alert.</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:12px; color:#64748b;">Report Generated</div>
                <div style="font-weight:600; font-size:13px;">{now_str}</div>
            </div>
        </div>

        <div class="meta-grid">
            <div class="meta-item">
                <div class="meta-label">Run ID</div>
                <div class="meta-val" style="font-family:monospace; font-size:13px;">{escape(run.run_id)}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Emails Scanned</div>
                <div class="meta-val">{run.emails_scanned}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Attachments Processed</div>
                <div class="meta-val">{run.attachments_processed}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">New Error Codes</div>
                <div class="meta-val"><span class="badge-new">{len(new_errors)} NEW</span></div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Known Codes Filtered</div>
                <div class="meta-val" style="color:#16a34a;">{len(existing_errors)} Existing</div>
            </div>
        </div>

        {ai_html}

        <div class="section-title">
            <span>OBSERVED FACTS — NEW ERROR OCCURRENCES ({len(new_errors)})</span>
            <span style="font-size:12px; font-weight:normal; color:#64748b;">Deterministic extraction & registry comparison</span>
        </div>

        <table>
            <thead>
                <tr>
                    <th style="width:140px;">Error Code</th>
                    <th style="width:90px;">Severity</th>
                    <th style="width:90px; text-align:center;">Occurrences</th>
                    <th style="width:200px;">Message</th>
                    <th>Observed Context</th>
                    <th style="width:220px;">Source Details</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div class="footer">
            <div>RSR ErrorSentinel AI Monitoring Agent</div>
            <div>Transactionally verified & registered</div>
        </div>
    </div>
</body>
</html>
"""
    return html


def save_reports(
    run: MonitoringRunModel,
    new_errors: list[ErrorRecord],
    existing_errors: list[ErrorRecord],
    ai_analysis: Optional[dict[str, Any]] = None,
    settings: Optional[Settings] = None,
) -> tuple[Path, Path]:
    """
    Saves HTML and JSON reports to configured reports_dir.
    Returns: (html_path, json_path)
    """
    cfg = settings or get_settings()
    out_dir = cfg.reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    html_content = generate_html_report(run, new_errors, existing_errors, ai_analysis, cfg)
    html_path = out_dir / f"report_{run.run_id}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    json_payload = {
        "run_id": run.run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "emails_scanned": run.emails_scanned,
            "emails_processed": run.emails_processed,
            "attachments_processed": run.attachments_processed,
            "new_errors_count": len(new_errors),
            "existing_errors_count": len(existing_errors),
            "duration_ms": run.duration_ms,
        },
        "ai_analysis": ai_analysis or {},
        "new_errors": [
            {
                "normalized_code": e.normalized_code,
                "raw_code": e.raw_code,
                "message": e.message,
                "severity": str(e.severity),
                "occurrence_count": e.occurrence_count,
                "context": e.context,
                "source_email": e.source_email,
                "sender": e.sender,
                "attachment_name": e.attachment_name,
                "source_type": e.source_type,
                "ai_confidence": e.ai_confidence,
            }
            for e in new_errors
        ],
        "existing_errors": [
            {
                "normalized_code": e.normalized_code,
                "occurrence_count": e.occurrence_count,
            }
            for e in existing_errors
        ],
    }

    json_path = out_dir / f"report_{run.run_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=2)

    logger.info(f"Saved run reports: HTML -> {html_path}, JSON -> {json_path}")
    return html_path, json_path
