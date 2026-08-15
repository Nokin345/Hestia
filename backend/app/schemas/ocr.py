from pydantic import BaseModel


class OcrConfigOut(BaseModel):
    url: str = ""
    model: str = ""
    has_api_key: bool = False


class OcrConfigUpdate(BaseModel):
    url: str | None = None
    model: str | None = None
    api_key: str | None = None


class OcrTestResult(BaseModel):
    ok: bool
    message: str
    backend: str
    model: str = ""
    fallback: bool = False
    remote_reachable: bool | None = None
