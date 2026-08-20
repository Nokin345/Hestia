from datetime import datetime

from pydantic import BaseModel, Field

MEMORY_CATEGORIES = ("fact", "event", "contact", "preference", "identity")


class MemoryCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    category: str = Field(default="fact")
    pinned: bool = False


class MemoryPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    category: str | None = None
    pinned: bool | None = None


class MemoryOut(BaseModel):
    id: str
    text: str
    category: str
    source: str
    uses: int
    pinned: bool
    conversation_id: str | None
    created_at: datetime
    updated_at: datetime
    last_recalled_at: datetime | None = None

    model_config = {"from_attributes": True}


class MemoryStats(BaseModel):
    total: int
    categories: dict[str, int]
