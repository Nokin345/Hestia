import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProviderConfig
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import Provider
from app.providers.gemini_provider import GeminiProvider
from app.providers.llamacpp_provider import LlamaCppProvider
from app.providers.ollama_provider import OllamaProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.openrouter_provider import OpenRouterProvider
from app.schemas.provider import ProviderModel

TYPE_DEFAULT_BASE_URL = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434",
    "llamacpp": "http://localhost:8080/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}


def build_provider(cfg: ProviderConfig) -> Provider:
    if cfg.type == "anthropic":
        return AnthropicProvider(cfg.api_key)
    if cfg.type == "gemini":
        return GeminiProvider(cfg.api_key)
    if cfg.type == "ollama":
        return OllamaProvider(
            cfg.api_key,
            base_url=cfg.base_url or TYPE_DEFAULT_BASE_URL.get("ollama"),
            id=cfg.id,
            name=cfg.name,
        )
    if cfg.type == "openrouter":
        return OpenRouterProvider(
            cfg.api_key,
            base_url=cfg.base_url or TYPE_DEFAULT_BASE_URL.get("openrouter"),
            id=cfg.id,
            name=cfg.name,
        )
    if cfg.type == "llamacpp":
        return LlamaCppProvider(
            cfg.api_key,
            base_url=cfg.base_url or TYPE_DEFAULT_BASE_URL.get("llamacpp"),
            id=cfg.id,
            name=cfg.name,
        )
    # Default: OpenAI
    return OpenAIProvider(
        cfg.api_key,
        base_url=cfg.base_url or TYPE_DEFAULT_BASE_URL.get("openai"),
        id=cfg.id,
        name=cfg.name,
    )


async def list_provider_configs(
    db: AsyncSession, only_enabled: bool = False
) -> list[ProviderConfig]:
    stmt = select(ProviderConfig).order_by(ProviderConfig.name)
    if only_enabled:
        stmt = stmt.where(ProviderConfig.enabled.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_provider_config(
    db: AsyncSession, provider_id: str
) -> ProviderConfig | None:
    return await db.get(ProviderConfig, provider_id)


async def get_provider(db: AsyncSession, provider_id: str) -> Provider | None:
    cfg = await get_provider_config(db, provider_id)
    if cfg is None or not cfg.enabled:
        return None
    return build_provider(cfg)


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "••••••••"
    return f"{key[:6]}••••{key[-4:]}"


def slugify(name: str) -> str:
    out = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
    return out or "provider"


def serialize_allowed(allowed: list[ProviderModel] | None) -> str | None:
    if allowed is None:
        return None

    def clean(m):
        data = m.model_dump() if hasattr(m, "model_dump") else dict(m)
        data.pop("available", None)
        data.pop("reason", None)
        return data

    return json.dumps(
        [clean(m) for m in allowed],
        ensure_ascii=False,
    )


def deserialize_allowed(raw: str | None) -> list[ProviderModel] | None:
    if raw is None:
        return None
    try:
        return [ProviderModel(**d) for d in json.loads(raw)]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
