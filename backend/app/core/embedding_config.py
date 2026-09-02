from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Setting

_CONFIG_KEYS = (
    "embedding_url",
    "embedding_model",
    "embedding_api_key",
)


@dataclass
class EmbeddingConfig:
    url: str = ""
    model: str = ""
    api_key: str = ""

    @property
    def use_remote(self) -> bool:
        return bool(self.url.strip())


async def load_embedding_config(db: AsyncSession) -> EmbeddingConfig:
    res = await db.execute(select(Setting).where(Setting.key.in_(_CONFIG_KEYS)))
    rows = {s.key: s.value for s in res.scalars()}
    # Env-provided values are auto-provisioned: if the admin never saved an
    # explicit value, the .env/compose settings become the effective defaults.
    # The normal fallbacks still apply at runtime (e.g. fastembed if the
    # remote endpoint is unreachable).
    settings = get_settings()
    url = (rows.get("embedding_url") or "").strip() or settings.embedding_url.strip()
    model = (rows.get("embedding_model") or "").strip() or settings.embedding_model.strip()
    api_key = (rows.get("embedding_api_key") or "").strip() or settings.embedding_api_key.strip()
    return EmbeddingConfig(url=url, model=model, api_key=api_key)
