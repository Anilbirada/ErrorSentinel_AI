from __future__ import annotations

import os
import re
from pathlib import Path
from app.config import get_settings

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".vbs", ".ps1", ".dll", ".so",
    ".dylib", ".msi", ".com", ".scr", ".pif", ".vbe", ".jse", ".wsf", ".wsh"
}

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".json",
    ".xml", ".txt", ".log", ".md", ".html", ".htm"
}


def safe_filename(name: str) -> str:
    """Sanitize filename against path traversal and dangerous characters."""
    clean = Path(name or "attachment").name
    clean = re.sub(r"[^A-Za-z0-9._ -]", "_", clean)
    clean = clean.strip(". ")
    return clean[:200] or "attachment.txt"


def validate_attachment_safety(filename: str, size_bytes: int) -> tuple[bool, str]:
    """
    Validate attachment against size limits and dangerous extensions.
    Never allows execution of macros, scripts, or arbitrary executable binaries.
    """
    settings = get_settings()
    max_bytes = settings.max_attachment_size_mb * 1024 * 1024

    if size_bytes > max_bytes:
        return False, f"File size ({size_bytes / (1024*1024):.2f}MB) exceeds configured limit of {settings.max_attachment_size_mb}MB"

    suffix = Path(filename).suffix.lower()
    if suffix in BLOCKED_EXTENSIONS:
        return False, f"Dangerous attachment type blocked: {suffix}"

    return True, "OK"


def is_safe_path(base_dir: Path, target_path: Path) -> bool:
    """Ensure target path stays strictly inside base directory."""
    try:
        base_dir.resolve()
        target_path.resolve().relative_to(base_dir.resolve())
        return True
    except (ValueError, RuntimeError):
        return False
