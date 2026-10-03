from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.extraction.text_extractors import (
    extract_csv,
    extract_docx,
    extract_excel,
    extract_json,
    extract_pdf,
    extract_txt,
    extract_xml,
)
from app.logging.logger import get_logger
from app.models.extraction import ExtractedDocument

logger = get_logger("document_dispatcher")


@dataclass
class LegacyExtractResult:
    text: str = ""
    warnings: list[str] = field(default_factory=list)


def extract_file(file_path: Path) -> LegacyExtractResult:
    """Legacy extraction function for unit test compatibility."""
    doc = extract_document(file_path, source_message_id="legacy")
    warnings = [doc.error_message] if doc.error_message else []
    return LegacyExtractResult(text=doc.text, warnings=warnings)


def extract_document(
    file_path: Path,
    source_message_id: str,
    mime_type: Optional[str] = None,
    file_hash: str = "",
) -> ExtractedDocument:
    """
    Extract text content from any supported file format.
    Never executes macro code or scripts.
    Handles invalid or corrupted files gracefully.
    """
    if not file_path.exists():
        return ExtractedDocument(
            filename=file_path.name,
            mime_type=mime_type or "unknown",
            source_message_id=source_message_id,
            text="",
            extraction_status="FAILED",
            error_message="File not found on disk",
            size=0,
            hash=file_hash,
            local_path=str(file_path),
        )

    file_size = file_path.stat().st_size
    suffix = file_path.suffix.lower()

    try:
        if suffix == ".pdf":
            text, meta = extract_pdf(file_path)
            page_count = meta.get("page_count", 1)
            sheet_count = 1
        elif suffix in (".docx", ".doc"):
            text, meta = extract_docx(file_path)
            page_count = 1
            sheet_count = 1
        elif suffix in (".xlsx", ".xls"):
            text, meta = extract_excel(file_path)
            page_count = 1
            sheet_count = meta.get("sheet_count", 1)
        elif suffix == ".csv":
            text, meta = extract_csv(file_path)
            page_count = 1
            sheet_count = 1
        elif suffix == ".json":
            text, meta = extract_json(file_path)
            page_count = 1
            sheet_count = 1
        elif suffix in (".xml", ".xhtml", ".svg"):
            text, meta = extract_xml(file_path)
            page_count = 1
            sheet_count = 1
        elif suffix in (".txt", ".log", ".md", ".ini", ".cfg", ".yaml", ".yml", ".env"):
            text, meta = extract_txt(file_path)
            page_count = 1
            sheet_count = 1
        else:
            # Fallback for unknown text-like documents
            logger.info(f"Using generic text extraction fallback for unsupported extension: {suffix}")
            text, meta = extract_txt(file_path)
            page_count = 1
            sheet_count = 1

        return ExtractedDocument(
            filename=file_path.name,
            mime_type=mime_type or "application/octet-stream",
            source_message_id=source_message_id,
            text=text,
            metadata=meta,
            page_count=page_count,
            sheet_count=sheet_count,
            extraction_status="SUCCESS",
            error_message=None,
            size=file_size,
            hash=file_hash,
            local_path=str(file_path),
        )

    except Exception as e:
        logger.error(f"Error extracting text from {file_path.name}: {str(e)}", exc_info=True)
        return ExtractedDocument(
            filename=file_path.name,
            mime_type=mime_type or "unknown",
            source_message_id=source_message_id,
            text="",
            extraction_status="FAILED",
            error_message=str(e),
            size=file_size,
            hash=file_hash,
            local_path=str(file_path),
        )
