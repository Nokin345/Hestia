"""OCR clients for image-based documents (scanned/image PDFs, photos).

Priority order based on settings:
  1. Remote OpenAI-compatible vision/OCR endpoint (chat completions) when ocr_url set
  2. Local RapidOCR (ONNX runtime, CPU, ~multilingual PaddleOCR models) as
     zero-config fallback — the OCR analogue of the fastembed embeddings fallback.

Remote OCR expects a chat-completions endpoint (llama.cpp / vLLM / Ollama)
serving a vision-language model (e.g. NuExtract3, Qwen-VL). Local RapidOCR
downloads its models on first use and runs entirely on CPU.
"""

import base64
import logging
import mimetypes

import httpx

from app.core.ocr_config import OcrConfig

logger = logging.getLogger(__name__)


def _image_mime(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    if mime == "image/jpg":
        mime = "image/jpeg"
    return mime


class RemoteOcrClient:
    """OpenAI-compatible vision model used as OCR (chat completions)."""

    def __init__(self, url: str, model: str, api_key: str = ""):
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
        )

    def extract(self, image_path: str, prompt: str = "") -> str:
        mime = _image_mime(image_path)
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        text = (
            prompt
            or "Extract all text from this image verbatim. Preserve reading order, "
            "paragraphs and table structure. Return only the extracted text."
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": text},
                ],
            }
        ]
        payload: dict = {"messages": messages}
        if self.model:
            payload["model"] = self.model
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        resp = self._client.post(f"{self.url}/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()


class LocalOcrClient:
    """Local CPU OCR via RapidOCR (ONNX runtime + PaddleOCR models).

    Downloads small ONNX models on first use, then runs entirely offline.
    Default PP-OCR models handle Latin + CJK text (multilingual enough for
    common scanned documents).
    """

    _engine = None

    def __init__(self, lang: str = "ch"):
        self.lang = lang
        self.model = "RapidOCR (PP-OCRv4, ONNX)"
        self._load()

    def _load(self) -> None:
        if LocalOcrClient._engine is not None:
            return
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise RuntimeError(
                "rapidocr is not installed. Install it (pip install rapidocr_onnxruntime) "
                "or configure a remote OCR endpoint."
            )
        LocalOcrClient._engine = RapidOCR()
        logger.info("RapidOCR loaded (CPU)")

    def extract(self, image_path: str, prompt: str = "") -> str:
        result, _elapsed = LocalOcrClient._engine(str(image_path))
        if not result:
            return ""
        lines = [str(item[1]) for item in result if item and len(item) > 1]
        return "\n".join(lines).strip()


def build_ocr_client(cfg: OcrConfig):
    """Factory: try remote HTTP first, fall back to local RapidOCR.

    Returns ``(client, backend)`` where backend is ``"remote"`` or
    ``"local"``, or ``(None, "none")`` if neither is available.
    """
    if cfg.use_remote:
        try:
            client = RemoteOcrClient(cfg.url, cfg.model, cfg.api_key)
            return client, "remote"
        except Exception as e:
            logger.warning("Remote OCR endpoint unavailable (%s); trying local", e)
    try:
        client = LocalOcrClient()
        return client, "local"
    except Exception as e:
        logger.error("Local OCR unavailable: %s", e)
        return None, "none"


def load_ocr_from_settings(settings) -> tuple[object | None, str]:
    """Build the effective OCR client from a Settings object (env defaults).

    Uses settings.ocr_url/ocr_model/ocr_api_key without needing a DB round-trip.
    Returns ``(client, backend)`` — used by ingestion paths that don't have a
    session (or that should honor env defaults).
    """
    if not settings:
        return None, "none"
    cfg = OcrConfig(
        url=settings.ocr_url or "",
        model=settings.ocr_model or "",
        api_key=settings.ocr_api_key or "",
    )
    return build_ocr_client(cfg)
