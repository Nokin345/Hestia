from pydantic import BaseModel, Field


class EmbeddingConfigOut(BaseModel):
    url: str = ""
    model: str = ""
    has_api_key: bool = False


class EmbeddingConfigUpdate(BaseModel):
    url: str | None = None
    model: str | None = None
    api_key: str | None = None


class EmbeddingTestResult(BaseModel):
    ok: bool
    message: str
    backend: str
    count: int = 0
    dimension: int | None = None
    model: str = ""
    fallback: bool = False
    remote_reachable: bool | None = None


class EmbeddingStatsOut(BaseModel):
    healthy: bool
    count: int
    lane: str | None = None
    model: str | None = None
    dimension: int | None = None