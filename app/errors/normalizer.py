from __future__ import annotations

import re


def normalize_code(raw_code: str) -> str:
    """
    Normalize error code string deterministically according to business rules:
    - Strips leading/trailing whitespace
    - Normalizes Unicode dash variants (en-dash, em-dash, figure dash, etc.) to standard hyphen '-'
    - Converts underscores and multiple spaces to standard hyphen or single space
    - Uppercases code prefixes (e.g. 'err-5021' -> 'ERR-5021')
    - Standardizes 'Error-5021', 'Error 5021' -> 'ERR-5021'
    """
    if not raw_code:
        return ""

    code = raw_code.strip()

    # Replace all Unicode dashes with ASCII hyphen '-'
    # \u2010 (hyphen), \u2011 (non-breaking hyphen), \u2012 (figure dash),
    # \u2013 (en dash), \u2014 (em dash), \u2015 (horizontal bar), \u2212 (minus sign)
    unicode_dashes = r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]"
    code = re.sub(unicode_dashes, "-", code)

    # Standardize 'ERROR <num>' or 'ERROR-<num>' -> 'ERR-<num>'
    error_prefix = re.match(r"(?i)^(?:error|err_code|err)\s*[-_ ]\s*(\d+)$", code)
    if error_prefix:
        return f"ERR-{error_prefix.group(1)}"

    # Standardize 'E <num>' or 'E-<num>' -> 'ERR-<num>'
    e_prefix = re.match(r"(?i)^e\s*[-_ ]\s*(\d+)$", code)
    if e_prefix:
        return f"ERR-{e_prefix.group(1)}"

    # Standardize 'HTTP <num>' -> 'HTTP-<num>'
    http_match = re.match(r"(?i)^http\s*[-_ ]?\s*(\d{3})$", code)
    if http_match:
        return f"HTTP-{http_match.group(1)}"

    # Standardize 'SQLSTATE <code5>' -> 'SQLSTATE-<code5>'
    sqlstate_match = re.match(r"(?i)^sqlstate\s*[:=\-_ ]?\s*([A-Za-z0-9]{5})$", code)
    if sqlstate_match:
        return f"SQLSTATE-{sqlstate_match.group(1).upper()}"

    # Standardize 'ORA <num>' -> 'ORA-<num>'
    ora_match = re.match(r"(?i)^ora\s*[-_ ]?\s*(\d{4,6})$", code)
    if ora_match:
        return f"ORA-{ora_match.group(1)}"

    # General cleanup: normalize underscores/hyphens and uppercase
    code = re.sub(r"[\s_]+", "-", code)
    code = re.sub(r"-+", "-", code)
    return code.upper()
