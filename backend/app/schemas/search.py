from pydantic import BaseModel, Field


class SearchConfigOut(BaseModel):
    searxng_url: str = ""
    max_results: int = Field(default=5, ge=1, le=50)
    fallback: bool = True
    fetch_urls: bool = True
    fetch_limit: int = Field(default=1, ge=1, le=10)
    max_chars_per_url: int = Field(default=4000, ge=500, le=50000)


class SearchConfigUpdate(BaseModel):
    searxng_url: str | None = None
    max_results: int | None = Field(default=None, ge=1, le=50)
    fallback: bool | None = None
    fetch_urls: bool | None = None
    fetch_limit: int | None = Field(default=None, ge=1, le=10)
    max_chars_per_url: int | None = Field(default=None, ge=500, le=50000)


class SearchTestRequest(BaseModel):
    searxng_url: str = ""
    max_results: int = Field(default=5, ge=1, le=50)
    fallback: bool = True


class SearchTestResult(BaseModel):
    ok: bool
    message: str
    engine: str
    results: int = 0
