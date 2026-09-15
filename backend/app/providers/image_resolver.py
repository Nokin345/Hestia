import base64
import io
import mimetypes
from pathlib import Path

from app.config import get_settings

MAX_HEIGHT = 1024


def _resize_image(data: bytes, mime: str) -> bytes:
    """Resize image to max 1024px height, preserving aspect ratio."""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if img.height <= MAX_HEIGHT:
        return data

    ratio = MAX_HEIGHT / img.height
    new_width = int(img.width * ratio)
    new_height = MAX_HEIGHT
    img = img.resize((new_width, new_height), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG" if img.mode == "RGBA" else "JPEG", quality=85)
    return buf.getvalue()


def resolve_image_to_base64(
    image_url: str | None, image_mime: str | None = None
) -> tuple[str, str] | None:
    """Return (mime, base64_data) for an image reference.

    Handles: data: URLs, local /uploads/... paths, and remote http(s) URLs.
    Images larger than 1024px tall are downscaled to save context window.
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
        data = path.read_bytes()
        if mime.startswith("image/"):
            data = _resize_image(data, mime)
        return mime, base64.b64encode(data).decode()

    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as resp:
        mime = image_mime or resp.headers.get("Content-Type") or "image/png"
        data = resp.read()
        if mime.startswith("image/"):
            data = _resize_image(data, mime)
        return mime, base64.b64encode(data).decode()