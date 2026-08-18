from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_vector import get_memory_store
from app.db import get_db
from app.schemas.embedding import EmbeddingStatsOut

router = APIRouter(prefix="/api/embeddings", tags=["embeddings"])


@router.get("/stats", response_model=EmbeddingStatsOut)
async def get_stats(db: AsyncSession = Depends(get_db)):
    store = await get_memory_store(db)
    stats = store.get_stats()
    return EmbeddingStatsOut(**stats)
