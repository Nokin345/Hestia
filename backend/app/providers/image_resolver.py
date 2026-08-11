import base64
import mimetypes
from pathlib import Path

from app.config import get_settings


def resolve_image_to_base64(image_url: str | None, image_mime: str | None = None) -> tuple[str, str] | None:
    """Return (mime, base64_data) for an image reference.

    Handles: data: URLs, local /uploads/... paths, and remote http(s) URLs.
    """
    url = image_url or ""
    if not url:
        return None
    if url.startswith("data:"):
        header, _, b64 = url.partition(",")
        mime = header[5:].split(";")[0] or "image/png"
        return mime, b64

    if url.startswith("/uploads/"):
        settings = get_settings()
        path = Path(settings.upload_dir) / url[len("/uploads/"):]
        if not path.is_file():
            return None
        mime = image_mime or mimetypes.guess_type(str(path))[0] or "image/png"
        return mime, base64.b64encode(path.read_bytes()).decode()

    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as resp:
        mime = image_mime or resp.headers.get("Content-Type") or "image/png"
        return mime, base64.b64encode(resp.read()).decode()
