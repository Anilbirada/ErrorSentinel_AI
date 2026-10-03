"""Structured-ish logging with rotation and secret redaction."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|authorization|refresh[_-]?token)\s*[=:]\s*)\S+")
_KEYLIKE = re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}\b")


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        msg = _SECRET.sub(r"\1[REDACTED]", msg)
        msg = _KEYLIKE.sub("[REDACTED]", msg)
        record.msg, record.args = msg, ()
        return True


def setup_logging(log_dir: str | Path, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("sentinel")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in (RotatingFileHandler(Path(log_dir) / "sentinel.log", maxBytes=2_000_000,
                                        backupCount=5, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(fmt)
        handler.addFilter(RedactingFilter())
        logger.addHandler(handler)
    return logger
