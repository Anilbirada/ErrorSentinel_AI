from __future__ import annotations

import re

# Deterministic error code patterns according to specification
# Captures structured codes like ERR-1234, ERROR 500, HTTP 404, SQLSTATE, ORA-*, and named Exceptions
DEFAULT_PATTERNS = [
    r"\b(?:ERR|ERROR|ERR_CODE|E)[-_ \u2013\u2014]?\d{3,8}\b",
    r"\bHTTP[-_ ]?[1-5]\d{2}\b",
    r"\bERROR\s+[1-5]\d{2}\b",
    r"\bSQLSTATE\s*[:=]?\s*[A-Za-z0-9]{5}\b",
    r"\bSQL[-_ ]?\d{3,8}\b",
    r"\bORA[-_ ]?\d{4,6}\b",
    r"\b[A-Za-z][A-Za-z0-9_.]*(?:Exception|Fault)\b",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in DEFAULT_PATTERNS]
