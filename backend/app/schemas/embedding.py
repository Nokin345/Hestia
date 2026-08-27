from pydantic import BaseModel


class EmbeddingStatsOut(BaseModel):
    healthy: bool
    count: int
    lane: str | None = None
    dimension: int | None = None
