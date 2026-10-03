from __future__ import annotations
from html import escape
from pathlib import Path
def render_report(run_id:str, mailbox:str, groups:dict[str,dict], new_codes:set[str]) -> str:
    rows=[]
    for code, group in sorted(groups.items()):
        f=group["finding"]; rows.append(f"<tr><td>{escape(code)}</td><td>{escape(f.severity)}</td><td>{group['occurrences']}</td><td>{escape(f.message)}</td><td>{escape(f.context[:500])}</td><td>{escape(', '.join(sorted(group['sources'])))}</td><td>{f.confidence:.2f}</td></tr>")
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>body{{font:14px Arial;color:#18212f;margin:32px}}h1{{color:#17365d}}.badge{{background:#e7f6ec;color:#176b3a;padding:5px 9px;border-radius:12px}}table{{width:100%;border-collapse:collapse}}th{{background:#17365d;color:#fff}}td,th{{padding:10px;border:1px solid #dbe2ea;text-align:left;vertical-align:top}}</style></head><body><h1>RSR ErrorSentinel AI</h1><h2>Outlook Error Intelligence Report</h2><p>Run: <b>{escape(run_id)}</b> · Mailbox: {escape(mailbox)} · <span class="badge">New codes: {len(new_codes)}</span></p><table><thead><tr><th>Error Code</th><th>Severity</th><th>Occurrences</th><th>Message</th><th>Context</th><th>Sources</th><th>Confidence</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="7">No errors found.</td></tr>'}</tbody></table></body></html>'''
def persist_report(directory:Path,run_id:str,html:str, data:dict)->tuple[Path,Path]:
    directory.mkdir(parents=True,exist_ok=True); hp=directory/f"{run_id}.html"; jp=directory/f"{run_id}.json"; hp.write_text(html,encoding="utf-8"); import json; jp.write_text(json.dumps(data,indent=2,default=str),encoding="utf-8"); return hp,jp
