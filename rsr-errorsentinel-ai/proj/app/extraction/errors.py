"""Stage 1: deterministic, configurable regex extraction."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..models import RawFinding

_DASH = r"[\s_\-\u2010-\u2015\u2212]*"


@dataclass
class PatternRule:
    name: str
    regex: str
    template: str            # canonical form; {0}=whole match, {1}=group 1
    severity: str = "MEDIUM"
    priority: int = 1        # 1 = coded errors, 2 = plain phrases (only used on lines with no coded error)
    ignore_case: bool = True


DEFAULT_RULES: list[PatternRule] = [
    PatternRule("err_code", rf"\b(?:ERR|ERROR){_DASH}(\d{{3,6}})\b(?![\-:/.]\d)", "ERR-{1}"),
    PatternRule("http_5xx", r"\bHTTP[\s/]*(5\d\d)\b", "HTTP-{1}", "HIGH"),
    PatternRule("http_4xx", r"\bHTTP[\s/]*(4\d\d)\b", "HTTP-{1}"),
    PatternRule("sqlstate", r"\bSQLSTATE[\s\[:=]*([0-9A-Z]{5})\]?", "SQLSTATE-{1}", "HIGH"),
    PatternRule("oracle", r"\bORA-(\d{4,5})\b", "ORA-{1}", "HIGH"),
    PatternRule("exception", r"\b([A-Z][A-Za-z0-9_]*(?:Exception|Error))\b", "EXC-{1}", ignore_case=False),
    PatternRule("phrase", r"\b(connection refused|authentication failure|database timeout|"
                          r"permission denied|out of memory)\b", "MSG-{1}", priority=2),
]
_URGENT = re.compile(r"\b(fatal|critical|crash(?:ed)?)\b", re.I)


def rules_from_json(path: str | Path, include_defaults: bool = True) -> list[PatternRule]:
    """Custom client patterns: [{"name","regex","template","severity","priority"}, ...]."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    custom = [PatternRule(**item) for item in data]
    for r in custom:
        re.compile(r.regex)  # fail fast on invalid patterns
    return (DEFAULT_RULES if include_defaults else []) + custom


class RegexErrorExtractor:
    def __init__(self, rules: list[PatternRule] | None = None) -> None:
        self.rules = rules if rules is not None else DEFAULT_RULES
        self._compiled = [(r, re.compile(r.regex, re.I if r.ignore_case else 0)) for r in self.rules]

    def extract(self, text: str) -> list[RawFinding]:
        findings: list[RawFinding] = []
        for line in text.splitlines():
            line_findings: list[RawFinding] = []
            for priority in sorted({r.priority for r in self.rules}):
                for rule, rx in self._compiled:
                    if rule.priority != priority:
                        continue
                    for m in rx.finditer(line):
                        groups = (m.group(0),) + m.groups()
                        canonical = rule.template.format(*groups)
                        message = line[m.end():].strip(" \t:-\u2013\u2014]")[:300] or line[:m.start()].strip()[:300]
                        severity = "HIGH" if _URGENT.search(line) and rule.severity == "MEDIUM" else rule.severity
                        line_findings.append(RawFinding(m.group(0).strip(), canonical, message,
                                                        line.strip()[:300], severity, rule=rule.name))
                if line_findings:   # lower-priority phrase rules are skipped when a coded error matched
                    break
            findings.extend(line_findings)
        return findings
