from pydantic import BaseModel

PROVIDER_TYPES = [
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "requires_base_url": False,
        "default_base_url": "https://openrouter.ai/api/v1",
    },
    {
        "id": "ollama",
        "name": "Ollama",
        "requires_base_url": False,
        "default_base_url": "http://localhost:11434",
    },
    {
        "id": "llamacpp",
        "name": "llama.cpp",
        "requires_base_url": False,
        "default_base_url": "http://localhost:8080/v1",
    },
    {
        "id": "openai_compat",
        "name": "Custom (OpenAI-compatible)",
        "requires_base_url": True,
        "default_base_url": "",
    },
]

PROVIDER_TYPE_IDS = {t["id"] for t in PROVIDER_TYPES}

KEYLESS_TYPES = {"ollama", "llamacpp", "openai_compat"}


class ProviderModel(BaseModel):
    id: str
    name: str = ""
    context_window: int | None = None
    vision: bool = False
    max_output: int | None = None
    available: bool = True
    reason: str = ""


class ProviderConfigCreate(BaseModel):
    id: str | None = None
    name: str
    type: str
    api_key: str
    base_url: str | None = None
    enabled: bool = True
    allowed_models: list[ProviderModel] | None = None


class ProviderConfigUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    allowed_models: list[ProviderModel] | None = None


class ProviderOut(BaseModel):
    id: str
    name: str
    type: str
    base_url: str | None = None
    api_key_masked: str = ""
    enabled: bool = True
    allowed_models: list[ProviderModel] | None = None


class ModelEntry(BaseModel):
    id: str
    provider_id: str
    provider_name: str
    vision: bool = False
    context_window: int | None = None


class ProviderTestRequest(BaseModel):
    type: str
    api_key: str
    base_url: str | None = None


class ProviderTestResponse(BaseModel):
    ok: bool
    message: str
    models: list[ProviderModel] = []
