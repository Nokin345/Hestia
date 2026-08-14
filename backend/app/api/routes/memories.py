from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import memory as memory_service
from app.db import get_db
from app.schemas.memory import MemoryCreate, MemoryOut, MemoryPatch, MemoryStats

router = APIRouter(prefix="/api/memories", tags=["memories"])


@router.get("", response_model=list[MemoryOut])
async def list_memories(db: AsyncSession = Depends(get_db)):
    return await memory_service.list_memories(db)


@router.post("", response_model=MemoryOut)
async def create_memory(
    body: MemoryCreate, db: AsyncSession = Depends(get_db)
):
    try:
        mem = await memory_service.create_memory(db, body, source="manual")
    except memory_service.PinLimitExceeded:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Maximum of 10 pinned memories",
        )
    if mem is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Memory text cannot be empty")
    return mem


@router.get("/stats", response_model=MemoryStats)
async def get_stats(db: AsyncSession = Depends(get_db)):
    return await memory_service.memory_stats(db)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def patch_memory(
    memory_id: str, body: MemoryPatch, db: AsyncSession = Depends(get_db)
):
    try:
        mem = await memory_service.update_memory(db, memory_id, body)
    except memory_service.PinLimitExceeded:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Maximum of 10 pinned memories",
        )
    if mem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return mem


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await memory_service.delete_memory(db, memory_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
