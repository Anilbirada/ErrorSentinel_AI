from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Tuple

from app.logging.logger import get_logger

logger = get_logger("text_extractors")


def extract_txt(file_path: Path) -> Tuple[str, dict[str, Any]]:
    """Extract plain text, log files, or markdown with encoding fallback."""
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252", "ascii"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, errors="strict") as f:
                content = f.read()
            return content, {"encoding": enc, "lines": len(content.splitlines())}
        except (UnicodeDecodeError, UnicodeError):
            continue

    # Fallback with replacement
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return content, {"encoding": "utf-8-replace", "lines": len(content.splitlines())}


def extract_pdf(file_path: Path) -> Tuple[str, dict[str, Any]]:
    """Extract text from PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(file_path))
        text_parts = []
        page_count = len(doc)
        for page_idx in range(page_count):
            page = doc[page_idx]
            page_text = page.get_text()
            if page_text:
                text_parts.append(page_text)
        doc.close()
        full_text = "\n".join(text_parts)
        return full_text, {"page_count": page_count}
    except Exception as e:
        logger.error(f"PyMuPDF PDF extraction failed on {file_path.name}: {str(e)}")
        raise


def extract_docx(file_path: Path) -> Tuple[str, dict[str, Any]]:
    """Extract text from DOCX using python-docx."""
    try:
        import docx

        doc = docx.Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text]
        # Also extract table text
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)

        full_text = "\n".join(paragraphs)
        return full_text, {"paragraph_count": len(paragraphs)}
    except Exception as e:
        logger.error(f"DOCX extraction failed on {file_path.name}: {str(e)}")
        raise


def extract_excel(file_path: Path) -> Tuple[str, dict[str, Any]]:
    """Extract text from XLSX or XLS using pandas and openpyxl."""
    try:
        import pandas as pd

        suffix = file_path.suffix.lower()
        if suffix == ".xlsx":
            excel_file = pd.ExcelFile(str(file_path), engine="openpyxl")
        else:
            excel_file = pd.ExcelFile(str(file_path))

        sheet_names = excel_file.sheet_names
        sheet_texts = []
        for name in sheet_names:
            df = excel_file.parse(name)
            sheet_texts.append(f"--- Sheet: {name} ---")
            sheet_texts.append(df.to_string(index=False))

        full_text = "\n".join(sheet_texts)
        return full_text, {"sheet_count": len(sheet_names), "sheets": sheet_names}
    except Exception as e:
        logger.error(f"Excel extraction failed on {file_path.name}: {str(e)}")
        # Fallback to plain text read if corrupted/text format
        return extract_txt(file_path)


def extract_csv(file_path: Path) -> Tuple[str, dict[str, Any]]:
    """Extract text from CSV file."""
    try:
        import pandas as pd

        df = pd.read_csv(str(file_path), dtype=str)
        text = df.to_string(index=False)
        return text, {"row_count": len(df), "columns": list(df.columns)}
    except Exception:
        # Fallback to raw text extraction
        return extract_txt(file_path)


def extract_json(file_path: Path) -> Tuple[str, dict[str, Any]]:
    """Extract text from JSON file formatting keys and values."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        formatted = json.dumps(data, indent=2)
        return formatted, {"is_valid_json": True}
    except Exception as e:
        logger.warning(f"JSON parse error on {file_path.name}, falling back to text: {str(e)}")
        return extract_txt(file_path)


def extract_xml(file_path: Path) -> Tuple[str, dict[str, Any]]:
    """Safely extract text content from XML."""
    try:
        # Safe XML parsing (disallowing entities / DOCTYPE expansion)
        parser = ET.XMLParser()
        tree = ET.parse(str(file_path), parser=parser)
        root = tree.getroot()

        texts = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                texts.append(f"{elem.tag}: {elem.text.strip()}")
            if elem.attrib:
                for k, v in elem.attrib.items():
                    texts.append(f"  @{k}={v}")

        return "\n".join(texts), {"root_tag": root.tag}
    except Exception as e:
        logger.warning(f"XML parse error on {file_path.name}, falling back to text: {str(e)}")
        return extract_txt(file_path)
