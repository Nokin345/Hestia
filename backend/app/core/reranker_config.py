from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Setting

_CONFIG_KEYS = (
    "reranker_url",
    "reranker_model",
    "reranker_api_key",
)


@dataclass
class RerankerConfig:
    url: str = ""
    model: str = ""
    api_key: str = ""

    @property
    def use_remote(self) -> bool:
        return bool(self.url.strip())


async def load_reranker_config(db: AsyncSession) -> RerankerConfig:
    res = await db.execute(select(Setting).where(Setting.key.in_(_CONFIG_KEYS)))
    rows = {s.key: s.value for s in res.scalars()}
    settings = get_settings()
    url = (rows.get("reranker_url") or "").strip() or settings.reranker_url.strip()
    model = (rows.get("reranker_model") or "").strip() or settings.reranker_model.strip()
    api_key = (rows.get("reranker_api_key") or "").strip() or settings.reranker_api_key.strip()
    return RerankerConfig(url=url, model=model, api_key=api_key)


async def save_reranker_config(
    db: AsyncSession,
    *,
    url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> RerankerConfig:
    updates = {
        "reranker_url": url,
        "reranker_model": model,
        "reranker_api_key": api_key,
    }
    for key, value in updates.items():
        if value is None:
            continue
        setting = await db.get(Setting, key)
        if setting is None:
            setting = Setting(key=key, value="")
            db.add(setting)
        setting.value = str(value)
    await db.commit()
    return await load_reranker_config(db)
