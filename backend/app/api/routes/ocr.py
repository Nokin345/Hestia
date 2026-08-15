import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ocr import LocalOcrClient, RemoteOcrClient, build_ocr_client
from app.core.ocr_config import OcrConfig, load_ocr_config, save_ocr_config
from app.db import get_db
from app.schemas.ocr import OcrConfigOut, OcrConfigUpdate, OcrTestResult

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


@router.get("/config", response_model=OcrConfigOut)
async def get_config(db: AsyncSession = Depends(get_db)):
    cfg = await load_ocr_config(db)
    return OcrConfigOut(url=cfg.url, model=cfg.model, has_api_key=bool(cfg.api_key))


@router.patch("/config", response_model=OcrConfigOut)
async def update_config(
    body: OcrConfigUpdate, db: AsyncSession = Depends(get_db)
):
    cfg = await save_ocr_config(
        db,
        url=body.url,
        model=body.model,
        api_key=body.api_key,
    )
    return OcrConfigOut(url=cfg.url, model=cfg.model, has_api_key=bool(cfg.api_key))


@router.post("/test", response_model=OcrTestResult)
async def test_ocr(
    file: UploadFile | None = File(default=None),
    url: str = Form(default=""),
    model: str = Form(default=""),
    api_key: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Probe the OCR backend without persisting.

    Builds the OCR client from the submitted settings, runs it against an
    optional uploaded test file (image or PDF), and reports which backend it
    used — falling back to local CPU when a remote endpoint is unreachable.
    """
    cfg = OcrConfig(
        url=(url or "").strip(),
        model=(model or "").strip(),
        api_key=api_key or "",
    )

    test_path: str | None = None
    if file is not None:
        ext = Path(file.filename or "").suffix.lower() or ".png"
        data = await file.read()
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            test_path = tmp.name

        # PDF test files are rendered to a PNG before OCR (image-only pages).
        if ext == ".pdf":
            rendered = _render_pdf_first_page(test_path)
            if rendered:
                try:
                    Path(test_path).unlink(missing_ok=True)
                except OSError:
                    pass
                test_path = rendered
            else:
                try:
                    Path(test_path).unlink(missing_ok=True)
                except OSError:
                    pass
                return OcrTestResult(
                    ok=False,
                    backend="none",
                    message="Could not render the uploaded PDF to an image for OCR.",
                )

    try:
        backend = "none"
        client = None
        fallback = False
        remote_reachable: bool | None = None
        error: str | None = None

        if cfg.use_remote:
            try:
                client = RemoteOcrClient(cfg.url, cfg.model, cfg.api_key)
                backend = "remote"
                remote_reachable = True
                if test_path is not None:
                    # Probe the remote endpoint by actually extracting.
                    client.extract(test_path)
            except Exception as e:
                # Remote unreachable — fall back to local CPU (like embeddings).
                error = str(e)
                remote_reachable = False
                try:
                    client, backend = build_ocr_client(OcrConfig())
                    fallback = True
                except Exception:
                    client, backend = None, "none"

        if client is None:
            try:
                client = LocalOcrClient()
                backend = "local"
            except Exception as e:
                return OcrTestResult(
                    ok=False,
                    backend="none",
                    message=(
                        f"No OCR backend available: {e}"
                        + (f". Remote error: {error}" if error else "")
                    ),
                )

        if test_path is None:
            # No file provided — report which backend is ready.
            msg = f"OCR backend ready ({backend})."
            if fallback:
                msg += f" Remote endpoint unreachable ({error[:200]}) — will fall back to local RapidOCR."
            return OcrTestResult(
                ok=True,
                backend=backend,
                model=getattr(client, "model", ""),
                remote_reachable=remote_reachable,
                fallback=fallback,
                message=msg,
            )

        text = client.extract(test_path)
        if not text:
            return OcrTestResult(
                ok=False,
                backend=backend,
                model=getattr(client, "model", ""),
                remote_reachable=remote_reachable,
                fallback=fallback,
                message=(
                    "OCR produced no text (image may be blank or unreadable)."
                    + (f" Remote error: {error[:200]}" if error else "")
                ),
            )
        msg = f"OCR extracted {len(text)} chars:\n{text[:300]}"
        if fallback:
            msg = (
                f"Remote OCR endpoint unreachable — used local RapidOCR instead. {msg}"
            )
        return OcrTestResult(
            ok=True,
            backend=backend,
            model=getattr(client, "model", ""),
            remote_reachable=remote_reachable,
            fallback=fallback,
            message=msg,
        )
    finally:
        if test_path:
            try:
                Path(test_path).unlink(missing_ok=True)
            except OSError:
                pass


def _render_pdf_first_page(pdf_path: str) -> str | None:
    """Render the first page of a PDF to a PNG (for OCR testing)."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            if not doc:
                return None
            page = doc[0]
            pix = page.get_pixmap(dpi=170)
            tmp_path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
            pix.save(tmp_path)
            return tmp_path
    except Exception:
        return None
