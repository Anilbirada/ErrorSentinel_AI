from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from app.config import get_settings


# Regular expressions for scrubbing sensitive tokens/passwords
SECRET_PATTERNS = [
    re.compile(r'(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{20,}'),
    re.compile(r'(?i)(client_secret\s*=\s*)[^\s&,;]+'),
    re.compile(r'(?i)(password\s*=\s*)[^\s&,;]+'),
    re.compile(r'(?i)(api[_-]?key\s*[:=]\s*)[^\s&,;]+'),
    re.compile(r'(?i)(refresh_token\s*[:=]\s*)[^\s&,;]+'),
    re.compile(r'(?i)(access_token\s*[:=]\s*)[^\s&,;]+'),
]


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern in SECRET_PATTERNS:
                record.msg = pattern.sub(r'\1[REDACTED]', record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: "[REDACTED]" if any(s in k.lower() for s in ["secret", "password", "key", "token"]) else v
                    for k, v in record.args.items()
                }
        return True


_initialized = False


def configure_logging(log_level: Optional[str] = None) -> logging.Logger:
    return setup_logging(log_level)


def setup_logging(log_level: Optional[str] = None) -> logging.Logger:
    global _initialized
    settings = get_settings()
    level_str = log_level or settings.log_level
    level = getattr(logging, level_str.upper(), logging.INFO)

    logger = logging.getLogger("errorsentinel")
    logger.setLevel(level)

    if not _initialized:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = settings.logs_dir / "errorsentinel.log"

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] [%(filename)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        redaction_filter = SecretRedactionFilter()

        # Rotating file handler (10MB max, 5 backups)
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction_filter)
        logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(redaction_filter)
        logger.addHandler(console_handler)

        _initialized = True

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    setup_logging()
    if name:
        return logging.getLogger(f"errorsentinel.{name}")
    return logging.getLogger("errorsentinel")
