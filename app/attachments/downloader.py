from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Optional

from app.attachments.security import safe_filename, validate_attachment_safety, is_safe_path
from app.config import Settings, get_settings
from app.logging.logger import get_logger
from app.models.email import EmailAttachment
from app.providers.base import EmailProvider

logger = get_logger("attachment_downloader")


async def save_attachment(
    content: bytes,
    filename: str,
    target_dir: Path,
    max_bytes: int,
) -> Path:
    """Async helper for saving raw attachment bytes with validation."""
    clean_name = safe_filename(filename)
    if len(content) > max_bytes:
        raise ValueError(f"Attachment exceeds maximum allowed size: {len(content)} > {max_bytes}")
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / clean_name
    out_path.write_bytes(content)
    return out_path


class AttachmentDownloader:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.download_dir = self.settings.downloads_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def download(
        self,
        provider: EmailProvider,
        message_id: str,
        attachment: EmailAttachment,
    ) -> tuple[Optional[Path], Optional[str], Optional[str]]:
        """
        Downloads and verifies an attachment.
        Returns: (local_path, sha256_hash, error_message)
        """
        clean_name = safe_filename(attachment.filename)
        is_safe, reason = validate_attachment_safety(clean_name, attachment.size)
        if not is_safe:
            logger.warning(f"Attachment {attachment.filename} rejected: {reason}")
            return None, None, reason

        # Create isolated message folder
        msg_folder = self.download_dir / safe_filename(message_id)
        msg_folder.mkdir(parents=True, exist_ok=True)
        target_path = msg_folder / f"{attachment.attachment_id[:12]}_{clean_name}"

        if not is_safe_path(self.download_dir, target_path):
            return None, None, "Path traversal attempt detected"

        try:
            # If attachment already has data loaded
            if attachment.data:
                with open(target_path, "wb") as f:
                    f.write(attachment.data)
            else:
                provider.download_attachment(message_id, attachment.attachment_id, target_path)

            # Compute SHA-256 hash
            hasher = hashlib.sha256()
            with open(target_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            file_hash = hasher.hexdigest()

            return target_path, file_hash, None

        except Exception as e:
            logger.error(f"Failed downloading attachment {attachment.filename}: {str(e)}", exc_info=True)
            return None, None, str(e)
