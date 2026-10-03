"""HTML + JSON report. Observed facts and AI interpretation are kept in separate sections."""
from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from .ai import AIAnalysis
from .models import ErrorRecord, iso


def build_report(run_id: str, started_at, stats: dict, new: list[ErrorRecord], existing: list[ErrorRecord],
                 failed_items: list[str], analysis: AIAnalysis | None) -> dict:
    return {
        "run_id": run_id,
        "monitoring_time": iso(started_at),
        "emails_scanned": stats["emails_scanned"],
        "emails_processed": stats["emails_processed"],
        "attachments_processed": stats["attachments_processed"],
        "new_error_count": len(new),
        "existing_error_count": len(existing),
        "severity_counts": dict(Counter(r.severity for r in new)),
        "failed_items": failed_items,
        "observed_facts": {
            "new_errors": [_row(r) for r in new],
            "existing_errors": [r.normalized_code for r in existing],
        },
        "ai_interpretation": ({"label": "AI assessment (unverified)", **analysis.model_dump()}
                              if analysis else None),
    }


def _row(r: ErrorRecord) -> dict:
    return {"error_code": r.normalized_code, "raw_code": r.raw_code, "message": r.message,
            "severity": r.severity, "occurrence_count": r.occurrence_count, "context": r.context,
            "source_email": r.source_message_id, "sender": r.source_email,
            "attachment": r.attachment_name or "(email body)", "timestamp": iso(r.first_seen_at),
            "sources": r.sources}


def render_html(rep: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td><b>{e(r['error_code'])}</b></td><td>{e(r['message'])}</td><td>{e(r['severity'])}</td>"
        f"<td>{r['occurrence_count']}</td><td>{e(r['context'])}</td><td>{e(r['source_email'])}</td>"
        f"<td>{e(r['sender'])}</td><td>{e(r['attachment'])}</td><td>{e(r['timestamp'])}</td></tr>"
        for r in rep["observed_facts"]["new_errors"])
    sev = ", ".join(f"{e(k)}: {v}" for k, v in rep["severity_counts"].items()) or "none"
    failed = "".join(f"<li>{e(x)}</li>" for x in rep["failed_items"]) or "<li>none</li>"
    ai = rep["ai_interpretation"]
    if ai:
        ai_html = (f"<p><i>{e(ai['label'])}. Not verified.</i></p><p>{e(ai['summary'])}</p>"
                   + "".join(f"<h4>{t}</h4><ul>{''.join(f'<li>{e(x)}</li>' for x in ai[k])}</ul>"
                             for t, k in (("Related groups", "groups"), ("Possible causes", "possible_causes"),
                                          ("Suggested investigation areas", "investigation_areas")) if ai[k]))
    else:
        ai_html = "<p>No AI interpretation available for this run.</p>"
    return f"""<html><body style="font-family:Arial,sans-serif;color:#222">
<h2>RSR ErrorSentinel AI &mdash; {rep['new_error_count']} New Error(s) Detected</h2>
<p>Run <b>{e(rep['run_id'])}</b> &middot; {e(rep['monitoring_time'])}<br>
Emails scanned: {rep['emails_scanned']} &middot; processed: {rep['emails_processed']} &middot;
attachments processed: {rep['attachments_processed']}<br>
Existing (already known) errors seen: {rep['existing_error_count']} &middot; Severity: {sev}</p>
<h3>Observed facts</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px">
<tr style="background:#eee"><th>Error Code</th><th>Message</th><th>Severity</th><th>Count</th><th>Context</th>
<th>Source Email</th><th>Sender</th><th>Attachment</th><th>Timestamp</th></tr>{rows}</table>
<h3>Failed items</h3><ul>{failed}</ul>
<h3>AI interpretation</h3>{ai_html}</body></html>"""


def write_reports(rep: dict, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path, json_path = out / f"{rep['run_id']}.html", out / f"{rep['run_id']}.json"
    html_path.write_text(render_html(rep), encoding="utf-8")
    json_path.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return html_path, json_path
