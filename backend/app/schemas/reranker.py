from pydantic import BaseModel


class RerankerConfigOut(BaseModel):
    url: str = ""
    model: str = ""
    has_api_key: bool = False


class RerankerConfigUpdate(BaseModel):
    url: str | None = None
    model: str | None = None
    api_key: str | None = None


class RerankerTestResult(BaseModel):
    ok: bool
    message: str
