"""Knowledge base document ingestion: text extraction + chunking.

Mirrors odysseus: PDF text via pypdf, overlapping character chunks
(CHUNK_SIZE=1000, CHUNK_OVERLAP=200).
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def extract_pdf_text(path: str | Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "".join((page.extract_text() or "") for page in reader.pages)
        return text
    except ImportError:
        logger.warning("pypdf not installed, cannot extract PDF text")
        return ""
    except Exception as e:
        logger.warning("Failed to extract PDF text from %s: %s", path, e)
        return ""


def extract_text(path: str | Path, mime: str) -> str:
    if mime == "application/pdf":
        return extract_pdf_text(path)
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        logger.warning("Failed to read %s: %s", path, e)
        return ""
    if data.startswith(b"\x00"):
        return ""
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def split_chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks (odysseus-compatible)."""
    if not isinstance(text, str):
        return []
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(i + size, n)
        chunks.append(text[i:j])
        if j >= n:
            break
        i = j - overlap if j - overlap > i else j
    return chunks
