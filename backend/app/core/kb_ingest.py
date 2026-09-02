"""Knowledge base document ingestion: text extraction + chunking.

Mirrors odysseus: PDF text via pypdf, overlapping character chunks
(CHUNK_SIZE=1000, CHUNK_OVERLAP=200).

PDFs without a text layer (scanned/image PDFs) are detected page-by-page and
fall back to OCR (remote VLM or local RapidOCR) when available.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# A page whose extracted text is below this many non-whitespace chars is
# treated as image-only (no text layer) and routed to OCR.
_MIN_TEXT_CHARS = 40


def _non_ws_len(text: str) -> int:
    return len("".join(text.split()))


def join_chunks(chunks: list[tuple[int, str]]) -> str:
    """Concatenate ordered chunks, stripping overlap only between consecutive ones.

    Each entry is ``(chunk_index, text)``.  Overlap is stripped from a chunk
    only when its index is exactly one greater than the previous chunk's index.
    A ``[...]`` marker is inserted when a gap is detected between chunks.
    """
    if not chunks:
        return ""
    parts: list[str] = [chunks[0][1]]
    for (prev_idx, _), (cur_idx, text) in zip(chunks, chunks[1:]):
        if cur_idx != prev_idx + 1:
            parts.append("[...]")
        if cur_idx == prev_idx + 1 and len(text) > CHUNK_OVERLAP:
            parts.append(text[CHUNK_OVERLAP:])
        else:
            parts.append(text)
    return "".join(parts)


def extract_pdf_text(path: str | Path, ocr=None, ocr_backend: str = "") -> str:
    """Extract PDF text via PyMuPDF (best), fallback pypdf, then OCR."""

    parts: list[str] = []
    for i in range(_page_count(path)):
        page_text = ""
        method = ""

        # 1. PyMuPDF (best text extraction with proper spacing)
        try:
            import fitz

            with fitz.open(str(path)) as doc:
                page = doc[i]
                page_text = page.get_text() or ""
                method = "pymupdf"
        except Exception:
            pass

        # 2. pypdf fallback (needs space fix)
        if not method or _non_ws_len(page_text) < _MIN_TEXT_CHARS:
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                page_text = reader.pages[i].extract_text() or ""
                method = "pypdf"
            except Exception:
                pass

        # 3. OCR fallback (scanned/image page)
        if not method or _non_ws_len(page_text) < _MIN_TEXT_CHARS:
            ocr_text = _ocr_pdf_page(str(path), i, ocr, ocr_backend)
            if ocr_text:
                page_text = ocr_text
                method = "ocr"

        if page_text.strip():
            parts.append(page_text.strip())
    return "\n\n".join(parts)


def _page_count(path: str | Path) -> int:
    try:
        import fitz

        with fitz.open(str(path)) as doc:
            return doc.page_count
    except Exception:
        try:
            from pypdf import PdfReader

            return len(PdfReader(str(path)).pages)
        except Exception:
            return 0


def _ocr_pdf_page(pdf_path: str, page_index: int, ocr, ocr_backend: str) -> str:
    """Render one PDF page to a PNG and run OCR on it."""
    if ocr is None:
        return ""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF not installed; cannot render PDF pages for OCR")
        return ""
    import tempfile

    try:
        with fitz.open(pdf_path) as doc:
            page = doc[page_index]
            pix = page.get_pixmap(dpi=170)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                pix.save(tmp_path)
            except Exception:
                return ""
        try:
            text = ocr.extract(tmp_path)
            if text:
                logger.info(
                    "OCR page %s of %s (%s backend), %s chars",
                    page_index + 1,
                    Path(pdf_path).name,
                    ocr_backend or "?",
                    len(text),
                )
            return text
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
    except Exception as e:
        logger.warning("OCR page %s failed for %s: %s", page_index, pdf_path, e)
        return ""


def extract_pdf_page(reader, pdf_path: str | Path, page_index: int, ocr=None, ocr_backend: str = "") -> tuple[str, str]:
    """Extract a single PDF page. Returns ``(text, method)``.

    Tries PyMuPDF first (best spacing), then pypdf, then OCR.
    ``method`` is ``"pymupdf"``, ``"pypdf"``, ``"ocr_local"``, or ``"ocr_remote"``.
    """
    page_text = ""

    # 1. PyMuPDF
    try:
        import fitz

        with fitz.open(str(pdf_path)) as doc:
            page_text = doc[page_index].get_text() or ""
    except Exception:
        pass
    if _non_ws_len(page_text) >= _MIN_TEXT_CHARS:
        return page_text, "pymupdf"

    # 2. pypdf fallback
    page_text = ""
    try:
        page_text = reader.pages[page_index].extract_text() or ""
    except Exception as e:
        logger.warning("PDF %s page %s text extraction failed: %s", pdf_path, page_index, e)
    if _non_ws_len(page_text) >= _MIN_TEXT_CHARS:
        return page_text, "pypdf"

    # 3. OCR fallback
    ocr_text = _ocr_pdf_page(str(pdf_path), page_index, ocr, ocr_backend)
    if ocr_text:
        return ocr_text, f"ocr_{ocr_backend}" if ocr_backend else "ocr"
    return "", "none"


def extract_text(path: str | Path, mime: str, ocr=None, ocr_backend: str = "") -> str:
    if mime == "application/pdf":
        return extract_pdf_text(path, ocr=ocr, ocr_backend=ocr_backend)
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
