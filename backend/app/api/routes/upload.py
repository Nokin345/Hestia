import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.config import get_settings
from app.db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/upload", tags=["upload"])

_ALLOWED_PREFIXES = ("image/",)
_ALLOWED_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/pdf",
    "application/json",
    "application/xml",
}

MAX_SIZE = 20 * 1024 * 1024  # 20 MB


def _allowed(mime: str) -> bool:
    return mime.startswith(_ALLOWED_PREFIXES) or mime in _ALLOWED_TYPES


@router.post("")
async def upload_file(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    mime = file.content_type or "application/octet-stream"
    if not _allowed(mime):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {mime}",
        )

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large (max 20 MB)",
        )

    ext = Path(file.filename or "").suffix or mimetypes.guess_extension(mime) or ""
    name = f"{uuid.uuid4().hex}{ext}"
    settings = get_settings()
    path = Path(settings.upload_dir) / name
    path.write_bytes(data)

    return {"url": f"/uploads/{name}", "mime": mime, "size": len(data)}
