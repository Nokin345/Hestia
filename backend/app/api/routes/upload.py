import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from app.config import get_settings
from app.db import get_db
from app.models import Conversation
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
    conversation_id: str | None = Form(default=None),
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

    settings = get_settings()
    upload_dir = Path(settings.upload_dir)

    # Group uploads under their conversation so deleting a conversation also
    # removes its attachments. Only nest when the conversation actually exists.
    if conversation_id:
        res = await db.execute(
            select(Conversation.id).where(Conversation.id == conversation_id)
        )
        if res.scalar_one_or_none() is not None:
            upload_dir = upload_dir / conversation_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "").suffix or mimetypes.guess_extension(mime) or ""
    name = f"{uuid.uuid4().hex}{ext}"
    path = upload_dir / name
    path.write_bytes(data)

    # Extract real text server-side so binaries (PDFs) aren't decoded as UTF-8
    # into gibberish. PDFs go through pypdf; plain text files are decoded.
    from app.core.kb_ingest import extract_text

    extracted = extract_text(path, mime) if not mime.startswith("image/") else ""
    if len(extracted) > 2_000_000:
        extracted = extracted[:2_000_000]

    if upload_dir == Path(settings.upload_dir):
        return {
            "url": f"/uploads/{name}",
            "mime": mime,
            "size": len(data),
            "text": extracted,
        }
    return {
        "url": f"/uploads/{conversation_id}/{name}",
        "mime": mime,
        "size": len(data),
        "text": extracted,
    }
