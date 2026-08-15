import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.kb_ingest import extract_text, split_chunks
from app.core.kb_vector import get_kb_store
from app.db import get_db
from app.models import KbDocument

router = APIRouter(prefix="/api/kb", tags=["kb"])

_ALLOWED_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/pdf",
    "application/json",
    "application/xml",
}

MAX_SIZE = 50 * 1024 * 1024  # 50 MB


class KbBulkRequest(BaseModel):
    ids: list[str]
    action: str  # "enable" | "disable" | "delete"


@router.post("")
async def upload_kb_document(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    mime = file.content_type or "application/octet-stream"
    if mime not in _ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {mime}")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    store = await get_kb_store(db)
    if not store.healthy:
        raise HTTPException(
            status_code=503,
            detail="Knowledge base embedding unavailable. Enable an embedding backend in Settings.",
        )

    settings = get_settings()
    kb_dir = Path(settings.upload_dir) / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "").suffix or ".bin"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = kb_dir / stored_name
    path.write_bytes(data)

    from app.core.kb_ingest import extract_text
    from app.core.ocr import build_ocr_client
    from app.core.ocr_config import load_ocr_config

    ocr, ocr_backend = None, ""
    if mime == "application/pdf":
        ocr_cfg = await load_ocr_config(db)
        ocr, ocr_backend = build_ocr_client(ocr_cfg)

    text = extract_text(path, mime, ocr=ocr, ocr_backend=ocr_backend)
    chunks = split_chunks(text)

    doc = KbDocument(
        filename=file.filename or stored_name,
        mime=mime,
        path=f"kb/{stored_name}",
        chunk_count=len(chunks),
        text_preview=chunks[0][:200] if chunks else "",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    store.add_document_chunks(doc.id, chunks, doc.filename)
    if not chunks:
        await db.delete(doc)
        await db.commit()
        try:
            path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=422, detail="Could not extract text from the document")

    return {
        "id": doc.id,
        "filename": doc.filename,
        "mime": doc.mime,
        "size": len(data),
        "chunk_count": doc.chunk_count,
        "url": f"/uploads/{doc.path}",
    }


@router.get("")
async def list_kb_documents(db: AsyncSession = Depends(get_db)):
    store = await get_kb_store(db)
    result = await db.execute(select(KbDocument).order_by(KbDocument.created_at.desc()))
    docs = result.scalars().all()
    return {
        "healthy": store.healthy,
        "stats": store.get_stats(),
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "mime": d.mime,
                "chunk_count": d.chunk_count,
                "enabled": d.enabled,
                "preview": d.text_preview,
                "created_at": d.created_at.isoformat(),
                "url": f"/uploads/{d.path}",
            }
            for d in docs
        ],
    }


@router.patch("/{doc_id}")
async def set_kb_document_enabled(
    doc_id: str,
    enabled: bool,
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(KbDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.enabled = enabled
    await db.commit()
    await db.refresh(doc)
    return {
        "id": doc.id,
        "filename": doc.filename,
        "enabled": doc.enabled,
    }


@router.post("/bulk")
async def bulk_kb_documents(body: KbBulkRequest, db: AsyncSession = Depends(get_db)):
    if body.action not in ("enable", "disable", "delete"):
        raise HTTPException(status_code=422, detail="Invalid action")
    if not body.ids:
        return {"updated": 0}
    result = await db.execute(select(KbDocument).where(KbDocument.id.in_(body.ids)))
    docs = list(result.scalars().all())
    if body.action == "delete":
        store = await get_kb_store(db)
        settings = get_settings()
        for doc in docs:
            store.remove_document(doc.id)
            await db.delete(doc)
            try:
                (Path(settings.upload_dir) / doc.path).unlink(missing_ok=True)
            except Exception:
                pass
    else:
        for doc in docs:
            doc.enabled = body.action == "enable"
    await db.commit()
    return {"updated": len(docs)}


@router.delete("/{doc_id}", status_code=204)
async def delete_kb_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    doc = await db.get(KbDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    store = await get_kb_store(db)
    store.remove_document(doc_id)
    await db.delete(doc)
    await db.commit()
    settings = get_settings()
    try:
        path = Path(settings.upload_dir) / doc.path
        path.unlink(missing_ok=True)
    except Exception:
        pass
